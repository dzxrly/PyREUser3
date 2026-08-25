"""Normalize JSON field values into packable RSZ value specifications.

This module owns schema-shaped value preparation.  Instance-table planning stays in
``plan.py`` while scalar binary encoding stays in ``writer.py``.
"""

from __future__ import annotations

from typing import Any

from .models import InstanceRef, PackError, RawArrayValue, StructValue
from ..enum_codec import bitset_enum_type, encode_bitset, encode_flags
from ..schema import ClassDef, FieldDef


class PackerValueMixin:
    """Prepare fields, references, structs, enums, and default values for packing."""

    def _prepare_fields(self, class_def: ClassDef, raw_fields: Any) -> dict[str, Any]:
        """Prepare one schema-defined field mapping for later binary writing."""

        if isinstance(raw_fields, dict):
            raw_fields = self._normalize_bitset_fields(class_def, raw_fields)
        if not isinstance(raw_fields, dict):
            value_fields = [
                field for field in class_def.fields if field.name in {"_Value", "value__"}
            ]
            if len(value_fields) == 1:
                raw_fields = {value_fields[0].name: raw_fields}
            else:
                raise PackError(f"class {class_def.name} expects object fields")

        prepared: dict[str, Any] = {}
        class_default_enum = getattr(self, "class_default_enums", {}).get(
            class_def.name
        )
        for field_def in class_def.fields:
            key = field_def.name or "unnamed"
            raw_value = raw_fields.get(key, self._default_value(field_def))
            if (
                class_default_enum in getattr(self, "enum_flags", set())
                and isinstance(raw_value, list)
                and key.strip("_").lower() in {"value", "enumvalue", "fixedid"}
            ):
                try:
                    raw_value = encode_flags(
                        raw_value, class_default_enum, self.member_lookup
                    )
                except ValueError as exc:
                    raise PackError(str(exc)) from exc
            prepared[key] = self._prepare_field_value(field_def, raw_value)
        return prepared

    def _prepare_field_value(self, field_def: FieldDef, raw_value: Any) -> Any:
        """Convert one raw JSON value according to its schema field definition."""

        enum_type = self._enum_type_for_field(field_def)
        if (
            not field_def.is_array
            and isinstance(raw_value, list)
            and enum_type is not None
            and enum_type in getattr(self, "enum_flags", set())
        ):
            try:
                return encode_flags(raw_value, enum_type, self.member_lookup)
            except ValueError as exc:
                raise PackError(str(exc)) from exc

        if field_def.is_array:
            if isinstance(raw_value, dict) and (
                "_raw_array_count" in raw_value or "_raw_array_hex" in raw_value
            ):
                return self._prepare_raw_array(field_def, raw_value)
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
            return self._prepare_object_ref(field_def, raw_value)
        if field_def.field_type == "Struct":
            return self._prepare_struct_value(field_def, raw_value)
        return raw_value

    @staticmethod
    def _prepare_raw_array(
        field_def: FieldDef, raw_value: dict[str, Any]
    ) -> RawArrayValue:
        """Validate and decode an explicitly preserved raw array payload."""

        expected_keys = {"_raw_array_count", "_raw_array_hex"}
        if set(raw_value) != expected_keys:
            raise PackError(
                f"raw array {field_def.name!r} must contain exactly "
                f"{sorted(expected_keys)}"
            )
        count = raw_value.get("_raw_array_count")
        payload_hex = raw_value.get("_raw_array_hex")
        if not isinstance(count, int) or count < 0:
            raise PackError(
                f"raw array {field_def.name!r} count must be non-negative"
            )
        if not isinstance(payload_hex, str):
            raise PackError(
                f"raw array {field_def.name!r} payload must be hexadecimal text"
            )
        try:
            payload = bytes.fromhex(payload_hex)
        except ValueError as exc:
            raise PackError(
                f"raw array {field_def.name!r} payload is not valid hexadecimal"
            ) from exc
        return RawArrayValue(count=count, payload=payload)

    def _enum_type_for_field(self, field_def: FieldDef) -> str | None:
        original = field_def.original_type
        if not isinstance(original, str):
            return None
        candidates = [original]
        if original.endswith("_Serializable"):
            candidates.append(f"{original[:-13]}_Fixed")
        if "Serializable" in original:
            candidates.append(original.replace("Serializable", "Fixed"))
        for candidate in candidates:
            if candidate in getattr(self, "enum_lookup", {}):
                return candidate
        return None

    def _bitset_enum_for_class_name(self, class_name: str) -> str | None:
        configured = getattr(self, "bitset_rules", {}).get(class_name)
        candidate = configured or bitset_enum_type(class_name)
        if candidate in getattr(self, "enum_lookup", {}):
            return candidate
        return None

    def _normalize_bitset_fields(
        self, class_def: ClassDef, raw_fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate readable/v2 Bitset virtual fields to the schema's raw word array."""

        enum_type = self._bitset_enum_for_class_name(class_def.name)
        if enum_type is None:
            return raw_fields
        out = dict(raw_fields)
        readable_labels = out.pop(enum_type, None)
        word_count = out.pop("_WordCount", None)
        max_element = out.get("_MaxElement")
        raw_value = out.get("_Value")
        labels = readable_labels
        if labels is None and isinstance(raw_value, list):
            if word_count is not None or any(
                not isinstance(item, int) for item in raw_value
            ):
                labels = raw_value
        if labels is None:
            return out
        if not isinstance(labels, list):
            raise PackError(f"{class_def.name} readable bitset value must be an array")
        if max_element is not None and not isinstance(max_element, int):
            raise PackError(f"{class_def.name} _MaxElement must be an integer")
        if word_count is not None and (
            not isinstance(word_count, int) or word_count < 0
        ):
            raise PackError(
                f"{class_def.name} _WordCount must be a non-negative integer"
            )
        try:
            out["_Value"] = encode_bitset(
                labels,
                enum_type,
                self.member_lookup,
                max_element=max_element,
                word_count=word_count,
            )
        except ValueError as exc:
            raise PackError(str(exc)) from exc
        return out

    def _prepare_object_ref(self, field_def: FieldDef, raw_value: Any) -> InstanceRef:
        """Turn nulls, explicit ids, or embedded nodes into an instance reference."""

        if raw_value is None:
            return InstanceRef(0)
        if isinstance(raw_value, dict) and isinstance(
            raw_value.get("ref_instance_id"), int
        ):
            return InstanceRef(raw_value["ref_instance_id"])

        expected_class = self._resolve_object_class(field_def.original_type)
        if isinstance(raw_value, dict):
            class_keys = [
                key
                for key in raw_value
                if isinstance(key, str) and key in self.typedb.name_to_hash
            ]
            if len(class_keys) == 1 and len(raw_value) == 1:
                return InstanceRef(self._plan_node(raw_value))
            if expected_class:
                return InstanceRef(self._plan_node(raw_value, expected_class))

        if expected_class:
            return InstanceRef(self._plan_node(raw_value, expected_class))
        raise PackError(
            f"cannot encode object field {field_def.name!r} of type "
            f"{field_def.original_type!r}"
        )

    def _resolve_object_class(self, original_type: str) -> str | None:
        """Resolve an object field's schema class, including Fixed wrappers."""

        if original_type in self.typedb.name_to_hash:
            return original_type
        if original_type.endswith("_Fixed"):
            candidate = f"{original_type[:-6]}_Serializable"
            if candidate in self.typedb.name_to_hash:
                return candidate
        return None

    def _prepare_struct_value(self, field_def: FieldDef, raw_value: Any) -> Any:
        """Prepare a known struct recursively or preserve an unknown raw struct."""

        if isinstance(raw_value, dict) and isinstance(raw_value.get("raw"), str):
            return raw_value
        struct_hash = self.typedb.resolve_struct_hash(field_def.original_type)
        if struct_hash is None:
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

    @staticmethod
    def _default_value(field_def: FieldDef) -> Any:
        """Return the zero/default JSON value for one missing schema field."""

        if field_def.is_array:
            return []
        if field_def.field_type == "Bool":
            return False
        if field_def.field_type in {"F32", "F64"}:
            return 0.0
        if field_def.field_type in {"String", "Resource", "C8", "RuntimeType"}:
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
