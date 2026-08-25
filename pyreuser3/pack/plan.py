"""Convert full repack JSON into a stable list of RSZ instance specifications.

Planning validates references, resolves class names to schema hashes, fills defaults for
missing fields, and rejects layouts that would be lossy to rebuild.
"""

from __future__ import annotations

from typing import Any

from .container import (
    parse_optional_u32,
    parse_path,
    parse_repack_container,
    parse_required_u32,
    validate_resource_metadata,
    validate_userdata_metadata,
)
from .models import (
    ExternalUserdataSpec,
    InstanceRef,
    InstanceSpec,
    PackError,
)
from .values import PackerValueMixin
from ..core import PACK_JSON_FORMATS
from ..schema import ClassDef


class PackerPlanMixin(PackerValueMixin):
    """Plan packable RSZ instances from a full repack-format JSON document."""

    def _is_pack_document(self, data: Any) -> bool:
        """Return whether the input is pack document.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            data (Any): JSON tree or binary payload consumed by this conversion step.

        Returns:
            bool: True when the inspected value matches the expected schema or metadata pattern; otherwise False.
        """
        return (
            isinstance(data, dict)
            and data.get("_format") in PACK_JSON_FORMATS
            and isinstance(data.get("_instances"), dict)
        )

    def _plan_repack_input(self, data: Any) -> list[int]:
        """Reject readable JSON and plan the only supported pack input shape."""

        if not self._is_pack_document(data):
            raise PackError(
                "packing requires repack JSON; readable JSON is read-only"
            )
        return self._plan_pack_document(data)

    def _plan_pack_document(self, data: dict[str, Any]) -> list[int]:
        """Validate one repack document and commit its binary-writing plan."""

        self._reject_unsupported_sections(data)
        container = parse_repack_container(data)
        instances_raw = data.get("_instances")
        if not isinstance(instances_raw, dict):
            raise PackError("pack JSON must contain an _instances object")

        ids = self._parse_dense_instance_ids(instances_raw)
        known_ids = set(ids)
        roots = self._parse_pack_roots(data.get("_roots"), known_ids)
        self._validate_pack_references(instances_raw, known_ids)
        instances = self._plan_instance_specs(instances_raw, ids)
        validate_userdata_metadata(container, instances)

        self.instances = instances
        self._prepare_instance_fields(instances_raw, ids)
        validate_resource_metadata(container, self.instances)
        self.container = container
        return roots

    @staticmethod
    def _reject_unsupported_sections(data: dict[str, Any]) -> None:
        """Fail before planning when export recorded non-rebuildable source data."""

        unsupported = data.get("_unsupported", [])
        if not unsupported:
            return
        if not isinstance(unsupported, list):
            raise PackError("pack JSON _unsupported must be an array")
        raise PackError(
            "pack JSON contains original data sections that the current "
            f"writer cannot rebuild: {unsupported}"
        )

    def _parse_dense_instance_ids(
        self, instances_raw: dict[str, Any]
    ) -> list[int]:
        """Require a dense instance table beginning with the null slot."""

        ids = self._parse_pack_instance_ids(instances_raw)
        if not ids or ids[0] != 0:
            raise PackError("pack JSON _instances must include null instance 0")
        expected = list(range(ids[-1] + 1))
        if ids != expected:
            missing = sorted(set(expected) - set(ids))
            raise PackError(f"pack JSON instance ids must be dense; missing: {missing}")
        return ids

    def _plan_instance_specs(
        self, instances_raw: dict[str, Any], ids: list[int]
    ) -> list[InstanceSpec | ExternalUserdataSpec | None]:
        """Resolve every declared instance to an external reference or schema class."""

        instances: list[InstanceSpec | ExternalUserdataSpec | None] = [
            None for _ in ids
        ]
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
                instances[idx] = ExternalUserdataSpec(
                    class_hash=parse_required_u32(
                        entry.get("_hash"), f"instance {idx} _hash"
                    ),
                    crc=parse_required_u32(
                        entry.get("_crc"), f"instance {idx} _crc"
                    ),
                    path=parse_path(entry.get("path"), f"instance {idx} path"),
                )
                continue
            instances[idx] = self._plan_schema_instance(idx, entry)
        return instances

    def _plan_schema_instance(
        self, idx: int, entry: dict[str, Any]
    ) -> InstanceSpec:
        """Resolve one ordinary instance entry against the type database."""

        class_name = entry.get("_class")
        if not isinstance(class_name, str) or not class_name:
            raise PackError(f"instance {idx} is missing _class")
        declared_crc = parse_optional_u32(entry.get("_crc"))
        fields = entry.get("fields", {})
        field_names = (
            {key for key in fields if isinstance(key, str)}
            if isinstance(fields, dict)
            else None
        )
        if self._bitset_enum_for_class_name(class_name) is not None:
            field_names = None
        resolved = self.typedb.get_class_for_fields(
            class_name,
            field_names=field_names,
            crc=declared_crc,
        )
        if resolved is None:
            raise PackError(
                f"class not found in schema for instance {idx}: {class_name}"
            )
        class_hash, class_def = resolved
        self._validate_declared_hash(idx, entry, class_hash, class_def.crc)
        return InstanceSpec(class_hash=class_hash, class_def=class_def)

    def _prepare_instance_fields(
        self, instances_raw: dict[str, Any], ids: list[int]
    ) -> None:
        """Validate and normalize the field payload for each schema-backed instance."""

        for idx in ids[1:]:
            entry = instances_raw[str(idx)]
            spec = self.instances[idx]
            if spec is None or isinstance(spec, ExternalUserdataSpec):
                continue
            fields = entry.get("fields", {})
            if not isinstance(fields, dict):
                raise PackError(f"instance {idx} fields must be an object")
            fields = self._normalize_bitset_fields(spec.class_def, fields)
            self._validate_known_fields(idx, spec.class_def, fields)
            before_count = len(self.instances)
            spec.fields = self._prepare_fields(spec.class_def, fields)
            if len(self.instances) != before_count:
                raise PackError(
                    f"instance {idx} contains embedded object data; "
                    "pack JSON object fields must use ref_instance_id"
                )

    def _parse_pack_instance_ids(self, instances_raw: dict[str, Any]) -> list[int]:
        """Parse pack instance ids.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            instances_raw (dict[str, Any]): Raw JSON instance table before validation and normalization.

        Returns:
            list[int]: Instance indexes collected from roots, references, or normalized JSON input.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
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
        """Parse pack roots.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            raw_roots (Any): Raw root-reference section from the exported JSON document.
            known_ids (set[int]): Collection of identifiers used for validation.

        Returns:
            list[int]: Instance indexes collected from roots, references, or normalized JSON input.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
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
        """Validate pack references.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            instances_raw (dict[str, Any]): Raw JSON instance table before validation and normalization.
            known_ids (set[int]): Collection of identifiers used for validation.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        for idx, entry in instances_raw.items():
            self._validate_ref_value(entry, known_ids, f"_instances.{idx}")

    def _validate_ref_value(self, value: Any, known_ids: set[int], path: str) -> None:
        """Validate ref value.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            known_ids (set[int]): Collection of identifiers used for validation.
            path (str): Filesystem path to validate or use.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
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
                # Some modern RE Engine data uses -1 as an explicit null Object
                # reference. Preserve that signed sentinel exactly; all other
                # non-table ids remain invalid.
                if ref_id == -1:
                    return
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
        """Validate declared hash.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            idx (int): RSZ instance index being parsed, planned, or written.
            entry (dict[str, Any]): Raw JSON entry describing an instance or tree node.
            class_hash (int): RE_RSZ type hash for a class.
            crc (int): Schema CRC/hash value that identifies a class definition.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
        declared_hash = parse_optional_u32(entry.get("_hash"))
        if declared_hash is not None and declared_hash != class_hash:
            raise PackError(
                f"instance {idx} _hash does not match schema class: "
                f"0x{declared_hash:08x} != 0x{class_hash:08x}"
            )
        declared_crc = parse_optional_u32(entry.get("_crc"))
        if declared_crc is not None and declared_crc != (crc & 0xFFFFFFFF):
            raise PackError(
                f"instance {idx} _crc does not match schema class: "
                f"0x{declared_crc:08x} != 0x{crc & 0xFFFFFFFF:08x}"
            )

    def _validate_known_fields(
        self, idx: int, class_def: ClassDef, raw_fields: dict[str, Any]
    ) -> None:
        """Validate known fields.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            idx (int): RSZ instance index being parsed, planned, or written.
            class_def (ClassDef): Schema class definition for an instance or struct.
            raw_fields (dict[str, Any]): Raw field mapping read from an exported instance or tree node.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
        allowed = {field.name or "unnamed" for field in class_def.fields}
        unknown = sorted(key for key in raw_fields if key not in allowed)
        if unknown:
            raise PackError(
                f"instance {idx} ({class_def.name}) contains unknown fields: {unknown}"
            )

    def _normalize_roots(self, data: Any) -> list[Any]:
        """Normalize roots.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            data (Any): JSON tree or binary payload consumed by this conversion step.

        Returns:
            list[Any]: Normalized JSON list ready for later traversal or packing.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise PackError("top-level JSON must be an object or a list of objects")

    def _plan_node(self, node: Any, expected_class: str | None = None) -> int:
        """Plan node.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            node (Any): Export tree node or scalar value being unwrapped.
            expected_class (str | None): Optional class name expected by the surrounding field schema.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
        class_name, fields = self._unwrap_node(node, expected_class)
        field_names = (
            {key for key in fields if isinstance(key, str)}
            if isinstance(fields, dict)
            else None
        )
        if self._bitset_enum_for_class_name(class_name) is not None:
            field_names = None
        resolved = self.typedb.get_class_for_fields(class_name, field_names=field_names)
        if resolved is None:
            raise PackError(f"class not found in schema: {class_name}")
        class_hash, class_def = resolved
        fields = self._normalize_bitset_fields(class_def, fields)

        spec = InstanceSpec(class_hash=class_hash, class_def=class_def)
        spec.fields = self._prepare_fields(class_def, fields)
        instance_id = len(self.instances)
        # Preserve instance numbering and reference identity; RSZ object links depend on
        # these indexes remaining stable.
        self.instances.append(spec)
        return instance_id

    def _unwrap_node(self, node: Any, expected_class: str | None) -> tuple[str, Any]:
        """Extract class name and field payload from an exported tree node.

        The method validates JSON shape before mutating instance plans so invalid edits fail
        early with actionable errors.

        Args:
            node (Any): Export tree node or scalar value being unwrapped.
            expected_class (str | None): Optional class name expected by the surrounding field schema.

        Returns:
            tuple[str, Any]: Resolved class name together with the node payload to process.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
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
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            return expected_class, node
        raise PackError(f"cannot infer class for node: {node!r}")
