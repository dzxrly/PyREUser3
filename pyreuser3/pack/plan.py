"""Planning helpers that turn JSON input into packable instances."""

from __future__ import annotations

from typing import Any

from .models import PACK_JSON_FORMAT, InstanceRef, InstanceSpec, PackError, StructValue
from ..schema import ClassDef, FieldDef


class PackerPlanMixin:
    """Mixin that plans packable instances from JSON input."""

    def _is_pack_document(self, data: Any) -> bool:
        """Internal helper for is pack document."""
        return (
            isinstance(data, dict)
            and data.get("_format") == PACK_JSON_FORMAT
            and isinstance(data.get("_instances"), dict)
        )

    def _plan_pack_document(self, data: dict[str, Any]) -> list[int]:
        """Internal helper for plan pack document."""
        unsupported = data.get("_unsupported", [])
        if unsupported:
            if not isinstance(unsupported, list):
                raise PackError("pack JSON _unsupported must be an array")
            raise PackError(
                "pack JSON contains original data sections that the current "
                f"writer cannot rebuild: {unsupported}"
            )

        instances_raw = data.get("_instances")
        if not isinstance(instances_raw, dict):
            raise PackError("pack JSON must contain an _instances object")

        ids = self._parse_pack_instance_ids(instances_raw)
        if not ids or ids[0] != 0:
            raise PackError("pack JSON _instances must include null instance 0")
        # Keep instance references stable while parsing or packing data.
        expected = list(range(ids[-1] + 1))
        if ids != expected:
            missing = sorted(set(expected) - set(ids))
            raise PackError(f"pack JSON instance ids must be dense; missing: {missing}")

        roots = self._parse_pack_roots(data.get("_roots"), set(ids))
        self._validate_pack_references(instances_raw, set(ids))
        self.instances = [None for _ in ids]

        # Keep instance references stable while parsing or packing data.
        for idx in ids[1:]:
            entry = instances_raw[str(idx)]
            if not isinstance(entry, dict):
                raise PackError(f"instance {idx} must be an object")
            if entry.get("_unparsed"):
                reason = entry.get("reason", "unparsed")
                raise PackError(
                    f"instance {idx} is unparsed and cannot be packed: {reason}"
                )
            if entry.get("_kind") == "userdata_reference":
                raise PackError(
                    f"instance {idx} is an external userdata reference; "
                    "the current writer cannot rebuild RSZ userdata tables"
                )
            class_name = entry.get("_class")
            if not isinstance(class_name, str) or not class_name:
                raise PackError(f"instance {idx} is missing _class")
            class_hash = self.typedb.name_to_hash.get(class_name)
            if class_hash is None:
                raise PackError(
                    f"class not found in schema for instance {idx}: {class_name}"
                )
            class_def = self.typedb.get_class(class_hash)
            if class_def is None:
                raise PackError(
                    f"class hash not found in schema for instance {idx}: {class_name}"
                )
            self._validate_declared_hash(idx, entry, class_hash, class_def.crc)
            self.instances[idx] = InstanceSpec(
                class_hash=class_hash, class_def=class_def
            )

        # Keep instance references stable while parsing or packing data.
        for idx in ids[1:]:
            entry = instances_raw[str(idx)]
            spec = self.instances[idx]
            if spec is None:
                continue
            fields = entry.get("fields", {})
            if not isinstance(fields, dict):
                raise PackError(f"instance {idx} fields must be an object")
            self._validate_known_fields(idx, spec.class_def, fields)
            before_count = len(self.instances)
            spec.fields = self._prepare_fields(spec.class_def, fields)
            if len(self.instances) != before_count:
                # Keep instance references stable while parsing or packing data.
                raise PackError(
                    f"instance {idx} contains embedded object data; "
                    "pack JSON object fields must use ref_instance_id"
                )
        return roots

    def _parse_pack_instance_ids(self, instances_raw: dict[str, Any]) -> list[int]:
        """Internal helper for parse pack instance ids."""
        ids: list[int] = []
        for key in instances_raw:
            try:
                idx = int(key)
            except (TypeError, ValueError) as exc:
                raise PackError(f"invalid instance id: {key!r}") from exc
            if idx < 0:
                raise PackError(f"instance id must be non-negative: {idx}")
            ids.append(idx)
        return sorted(ids)

    def _parse_pack_roots(self, raw_roots: Any, known_ids: set[int]) -> list[int]:
        """Internal helper for parse pack roots."""
        if not isinstance(raw_roots, list):
            raise PackError("pack JSON must contain a _roots array")
        roots: list[int] = []
        for raw_root in raw_roots:
            if not isinstance(raw_root, int):
                raise PackError(f"root instance id must be int: {raw_root!r}")
            if raw_root not in known_ids:
                raise PackError(f"root references missing instance: {raw_root}")
            roots.append(raw_root)
        return roots

    def _validate_pack_references(
        self, instances_raw: dict[str, Any], known_ids: set[int]
    ) -> None:
        """Internal helper for validate pack references."""
        for idx, entry in instances_raw.items():
            self._validate_ref_value(entry, known_ids, f"_instances.{idx}")

    def _validate_ref_value(self, value: Any, known_ids: set[int], path: str) -> None:
        """Internal helper for validate ref value."""
        if isinstance(value, dict):
            if "ref_instance_id" in value:
                ref_id = value.get("ref_instance_id")
                if not isinstance(ref_id, int):
                    raise PackError(f"{path}.ref_instance_id must be int")
                extra = sorted(k for k in value if k != "ref_instance_id")
                if extra:
                    raise PackError(
                        f"{path} has ref_instance_id plus ignored keys: {extra}"
                    )
                if ref_id not in known_ids:
                    raise PackError(f"{path} references missing instance: {ref_id}")
                return
            for key, child in value.items():
                self._validate_ref_value(child, known_ids, f"{path}.{key}")
            return
        if isinstance(value, list):
            for i, child in enumerate(value):
                self._validate_ref_value(child, known_ids, f"{path}[{i}]")

    def _validate_declared_hash(
        self, idx: int, entry: dict[str, Any], class_hash: int, crc: int
    ) -> None:
        """Internal helper for validate declared hash."""
        declared_hash = self._parse_optional_u32(entry.get("_hash"))
        if declared_hash is not None and declared_hash != class_hash:
            raise PackError(
                f"instance {idx} _hash does not match schema class: "
                f"0x{declared_hash:08x} != 0x{class_hash:08x}"
            )
        declared_crc = self._parse_optional_u32(entry.get("_crc"))
        if declared_crc is not None and declared_crc != (crc & 0xFFFFFFFF):
            raise PackError(
                f"instance {idx} _crc does not match schema class: "
                f"0x{declared_crc:08x} != 0x{crc & 0xFFFFFFFF:08x}"
            )

    def _parse_optional_u32(self, value: Any) -> int | None:
        """Internal helper for parse optional u32."""
        if value is None:
            return None
        if isinstance(value, int):
            return value & 0xFFFFFFFF
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            return int(text, 0) & 0xFFFFFFFF
        raise PackError(f"expected integer or hex string, got {value!r}")

    def _validate_known_fields(
        self, idx: int, class_def: ClassDef, raw_fields: dict[str, Any]
    ) -> None:
        """Internal helper for validate known fields."""
        allowed = {field.name or "unnamed" for field in class_def.fields}
        unknown = sorted(key for key in raw_fields if key not in allowed)
        if unknown:
            raise PackError(
                f"instance {idx} ({class_def.name}) contains unknown fields: {unknown}"
            )

    def _normalize_roots(self, data: Any) -> list[Any]:
        """Internal helper for normalize roots."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise PackError("top-level JSON must be an object or a list of objects")

    def _plan_node(self, node: Any, expected_class: str | None = None) -> int:
        """Internal helper for plan node."""
        class_name, fields = self._unwrap_node(node, expected_class)
        class_hash = self.typedb.name_to_hash.get(class_name)
        if class_hash is None:
            raise PackError(f"class not found in schema: {class_name}")
        class_def = self.typedb.get_class(class_hash)
        if class_def is None:
            raise PackError(f"class hash not found in schema: {class_name}")

        spec = InstanceSpec(class_hash=class_hash, class_def=class_def)
        spec.fields = self._prepare_fields(class_def, fields)
        instance_id = len(self.instances)
        # Keep instance references stable while parsing or packing data.
        self.instances.append(spec)
        return instance_id

    def _unwrap_node(self, node: Any, expected_class: str | None) -> tuple[str, Any]:
        """Internal helper for unwrap node."""
        if isinstance(node, dict):
            class_keys = [
                k
                for k in node.keys()
                if isinstance(k, str) and k in self.typedb.name_to_hash
            ]
            if len(class_keys) == 1 and len(node) == 1:
                key = class_keys[0]
                return key, node[key]
        if expected_class:
            # Preserve field layout details for binary compatibility.
            return expected_class, node
        raise PackError(f"cannot infer class for node: {node!r}")

    def _prepare_fields(self, class_def: ClassDef, raw_fields: Any) -> dict[str, Any]:
        """Internal helper for prepare fields."""
        if not isinstance(raw_fields, dict):
            value_fields = [
                f for f in class_def.fields if f.name in {"_Value", "value__"}
            ]
            if len(value_fields) == 1:
                # Keep enum metadata consistent while converting values.
                raw_fields = {value_fields[0].name: raw_fields}
            else:
                raise PackError(f"class {class_def.name} expects object fields")

        prepared: dict[str, Any] = {}
        for field_def in class_def.fields:
            key = field_def.name or "unnamed"
            # Preserve field layout details for binary compatibility.
            raw_value = raw_fields.get(key, self._default_value(field_def))
            prepared[key] = self._prepare_field_value(field_def, raw_value)
        return prepared

    def _prepare_field_value(self, field_def: FieldDef, raw_value: Any) -> Any:
        """Internal helper for prepare field value."""
        if field_def.is_array:
            items = raw_value if isinstance(raw_value, list) else []
            non_array = FieldDef(
                name=field_def.name,
                field_type=field_def.field_type,
                original_type=field_def.original_type,
                size=field_def.size,
                align=field_def.align,
                is_array=False,
            )
            return [self._prepare_field_value(non_array, item) for item in items]

        if field_def.field_type in {"Object", "UserData"}:
            # Keep instance references stable while parsing or packing data.
            return self._prepare_object_ref(field_def, raw_value)
        if field_def.field_type == "Struct":
            # Preserve field layout details for binary compatibility.
            return self._prepare_struct_value(field_def, raw_value)
        return raw_value

    def _prepare_object_ref(self, field_def: FieldDef, raw_value: Any) -> InstanceRef:
        """Internal helper for prepare object ref."""
        if raw_value is None:
            return InstanceRef(0)
        if isinstance(raw_value, dict) and isinstance(
            raw_value.get("ref_instance_id"), int
        ):
            # Keep instance references stable while parsing or packing data.
            return InstanceRef(raw_value["ref_instance_id"])

        expected_class = self._resolve_object_class(field_def.original_type)
        if isinstance(raw_value, dict):
            class_keys = [
                k
                for k in raw_value.keys()
                if isinstance(k, str) and k in self.typedb.name_to_hash
            ]
            if len(class_keys) == 1 and len(raw_value) == 1:
                # Preserve field layout details for binary compatibility.
                return InstanceRef(self._plan_node(raw_value))
            if expected_class:
                return InstanceRef(self._plan_node(raw_value, expected_class))

        if expected_class:
            return InstanceRef(self._plan_node(raw_value, expected_class))
        raise PackError(
            f"cannot encode object field {field_def.name!r} of type {field_def.original_type!r}"
        )

    def _resolve_object_class(self, original_type: str) -> str | None:
        """Internal helper for resolve object class."""
        if original_type in self.typedb.name_to_hash:
            return original_type
        if original_type.endswith("_Fixed"):
            # Keep enum metadata consistent while converting values.
            candidate = f"{original_type[:-6]}_Serializable"
            if candidate in self.typedb.name_to_hash:
                return candidate
        return None

    def _prepare_struct_value(self, field_def: FieldDef, raw_value: Any) -> Any:
        """Internal helper for prepare struct value."""
        if isinstance(raw_value, dict) and isinstance(raw_value.get("raw"), str):
            # Preserve field layout details for binary compatibility.
            # Preserve field layout details for binary compatibility.
            return raw_value
        struct_hash = self.typedb.resolve_struct_hash(field_def.original_type)
        if struct_hash is None:
            # Preserve field layout details for binary compatibility.
            return StructValue(
                class_def=ClassDef(field_def.original_type, 0, []),
                fields={"raw": raw_value},
                declared_size=field_def.size,
            )
        class_def = self.typedb.get_class(struct_hash)
        if class_def is None:
            raise PackError(f"struct class not found: {field_def.original_type}")
        fields = raw_value if isinstance(raw_value, dict) else {}
        return StructValue(
            class_def, self._prepare_fields(class_def, fields), field_def.size
        )

    def _default_value(self, field_def: FieldDef) -> Any:
        """Internal helper for default value."""
        if field_def.is_array:
            return []
        if field_def.field_type in {"Bool"}:
            return False
        if field_def.field_type in {"F32", "F64"}:
            return 0.0
        if field_def.field_type in {"String", "Resource", "C8"}:
            return ""
        if field_def.field_type in {"Guid", "GameObjectRef", "Uri"}:
            return "00000000-0000-0000-0000-000000000000"
        if field_def.field_type in {"Object", "UserData"}:
            return None
        if field_def.field_type in {
            "Float2",
            "Float3",
            "Float4",
            "Vec2",
            "Vec3",
            "Vec4",
            "Quaternion",
            "Color",
            "AABB",
            "Capsule",
            "OBB",
            "Mat3",
            "Mat4",
            "Position",
        }:
            return [0.0 for _ in range(max(field_def.size // 4, 1))]
        return 0
