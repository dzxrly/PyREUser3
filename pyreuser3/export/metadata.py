"""Build enum lookup tables and contextual field hints from il2cpp dump metadata.

The exporter uses this context to decide which numeric fields can safely be rendered as
fixed enum labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core import ParseError, enum_storage_type_from_size
from ..rich_ui import get_console


class ExporterMetadataMixin:
    """Load enum metadata, fixed-id context, and lookup tables used while exporting readable
    JSON.
    """

    @staticmethod
    def _id_formatter(key: str, value: int) -> str:
        """Build a stable identifier formatter for enum metadata keys.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            key (str): Payload key, metadata key, or enum key being read.
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            str: Normalized or formatted text.
        """
        return f"[{value}] {key}"

    @staticmethod
    def _to_u32(value: int) -> int:
        """Normalize an integer-like value into an unsigned 32-bit integer.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """Normalize an integer-like value into a signed 32-bit integer.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000

    def _build_enum_lookup_from_enums_internal(
        self, raw: Any
    ) -> dict[str, dict[int, tuple[str, int]]]:
        """Build enum lookup from enums internal.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            raw (Any): Raw metadata, JSON, or binary value being normalized.

        Returns:
            dict[str, dict[int, tuple[str, int]]]: Enum lookup table keyed by type name and numeric value.
        """
        lookup: dict[str, dict[int, tuple[str, int]]] = {}
        if not isinstance(raw, dict):
            return lookup

        for enum_type, members in raw.items():
            if (
                not isinstance(enum_type, str)
                or not isinstance(members, dict)
            ):
                continue
            value_map: dict[int, tuple[str, int]] = {}
            for member_name, raw_value in members.items():
                if not isinstance(member_name, str) or not isinstance(raw_value, int):
                    continue
                entry = (member_name, raw_value)
                # Preserve the exported JSON structure so external scripts and hand-
                # edited files remain compatible across workflows.
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                value_map[raw_value] = entry
                value_map[self._to_s32(raw_value)] = entry
                value_map[self._to_u32(raw_value)] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """Load enum lookup.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            dict[str, dict[int, tuple[str, int]]]: Enum lookup table keyed by type name and numeric value.
        """
        return {}

    def _resolve_il2cpp_dump_path(self) -> Path | None:
        """Resolve il2cpp dump path.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            Path | None: Resolved path when the configured file exists; otherwise None.
        """
        return self.il2cpp_dump_path if self.il2cpp_dump_path.is_file() else None

    def _ensure_internal_metadata_files(self) -> dict:
        """Ensure internal metadata files.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            dict: Mapping populated from schema, enum, or job metadata.

        Raises:
            FileNotFoundError: A required file or directory was missing.
            ParseError: Binary data did not match the expected .user.3 or RSZ layout.
        """
        dump_path = self._resolve_il2cpp_dump_path()
        if dump_path is None:
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        try:
            enums_internal, enum_context = self.export_il2cpp_metadata_from_path(
                dump_path
            )
        except Exception as exc:
            raise ParseError(f"failed to read il2cpp dump: {dump_path}") from exc

        self.output_root.mkdir(parents=True, exist_ok=True)
        enums_out = self.output_root / "Enums_Internal.json"
        self._pending_enum_context = enum_context
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        with enums_out.open("w", encoding="utf-8") as f:
            json.dump(enums_internal, f, ensure_ascii=False, indent=2)
        return enums_internal

    def _rebuild_enum_member_index(self) -> None:
        """Rebuild reverse enum-member indexes used for numeric packing from labels.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.enum_member_to_types = {}
        for enum_type, value_map in self.enum_lookup.items():
            if not isinstance(enum_type, str) or not isinstance(value_map, dict):
                continue
            for member_name, _entry in value_map.values():
                if not isinstance(member_name, str):
                    continue
                types = self.enum_member_to_types.setdefault(member_name, [])
                if enum_type not in types:
                    types.append(enum_type)

    def _infer_enum_type_from_member_and_value(
        self, member_name: str, value: int
    ) -> str | None:
        """Infer enum type from member and value.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            member_name (str): Enum member label being resolved back to a numeric value.
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            str | None: Resolved string when a match is available; otherwise None.
        """
        candidates = self.enum_member_to_types.get(member_name)
        if not candidates:
            return None
        matched: list[str] = []
        for enum_type in candidates:
            value_map = self.enum_lookup.get(enum_type)
            if value_map is None:
                continue
            if (
                value in value_map
                or self._to_s32(value) in value_map
                or self._to_u32(value) in value_map
            ):
                matched.append(enum_type)
        if len(matched) == 1:
            return matched[0]
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        return None

    def _apply_enum_context(self, raw: dict) -> None:
        """Apply enum context.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            raw (dict): Raw metadata, JSON, or binary value being normalized.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.class_field_fixed_types = {}
        self.serializable_to_fixed = {}
        self.generic_container_rules = {}
        self.param_type_default_enum = {}
        self.enum_underlying_types = {}

        class_field_fixed_types = raw.get("class_field_fixed_types")
        if isinstance(class_field_fixed_types, dict):
            for cls_name, field_map in class_field_fixed_types.items():
                if not isinstance(cls_name, str) or not isinstance(field_map, dict):
                    continue
                cleaned: dict[str, str] = {}
                for field_name, enum_type in field_map.items():
                    # Register enum values through the shared lookup tables so readable
                    # labels and numeric packing stay reversible.
                    if (
                        isinstance(field_name, str)
                        and isinstance(enum_type, str)
                    ):
                        cleaned[field_name] = enum_type
                if cleaned:
                    self.class_field_fixed_types[cls_name] = cleaned

        enum_underlying_types = raw.get("enum_underlying_types")
        if isinstance(enum_underlying_types, dict):
            for enum_name, storage_type in enum_underlying_types.items():
                if (
                    isinstance(enum_name, str)
                    and isinstance(storage_type, str)
                    and storage_type in {"S8", "U8", "S16", "U16", "S32", "U32", "S64", "U64"}
                ):
                    self.enum_underlying_types[enum_name] = storage_type

        serializable_to_fixed = raw.get("serializable_to_fixed")
        if isinstance(serializable_to_fixed, dict):
            for serializable_name, fixed_name in serializable_to_fixed.items():
                if (
                    isinstance(serializable_name, str)
                    and isinstance(fixed_name, str)
                    and fixed_name.endswith("_Fixed")
                ):
                    self.serializable_to_fixed[serializable_name] = fixed_name

        generic_container_rules = raw.get("generic_container_rules")
        # Register enum values through the shared lookup tables so readable labels and
        # numeric packing stay reversible.
        param_to_enum_sets: dict[str, set[str]] = {}
        if isinstance(generic_container_rules, dict):
            for container_name, rule in generic_container_rules.items():
                if not isinstance(container_name, str) or not isinstance(rule, dict):
                    continue
                param_type = rule.get("param_type")
                enum_type = rule.get("enum_type")
                if (
                    isinstance(param_type, str)
                    and isinstance(enum_type, str)
                    and enum_type.endswith("_Fixed")
                ):
                    self.generic_container_rules[container_name] = (
                        param_type,
                        enum_type,
                    )
                    param_to_enum_sets.setdefault(param_type, set()).add(enum_type)

        for param_type, enum_types in param_to_enum_sets.items():
            if len(enum_types) == 1:
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                self.param_type_default_enum[param_type] = next(iter(enum_types))

    def _enum_type_candidates_for_lookup(self, type_name: str) -> list[str]:
        """Yield enum lookup candidates for schema or il2cpp type names."""
        candidates = [type_name]
        direct = self.serializable_to_fixed.get(type_name)
        if direct is not None:
            candidates.append(direct)
        if type_name.endswith("_Serializable"):
            candidates.append(f"{type_name[:-13]}_Fixed")
        if "Serializable" in type_name:
            candidates.append(type_name.replace("Serializable", "Fixed"))
        return list(dict.fromkeys(candidates))

    def _resolve_enum_type_for_lookup(self, type_name: str) -> str | None:
        """Resolve a schema enum type name to an available enum lookup key."""
        if not isinstance(type_name, str) or not type_name:
            return None
        for candidate in self._enum_type_candidates_for_lookup(type_name):
            if candidate in self.enum_lookup:
                return candidate
        return None

    def _resolve_enum_storage_type(self, field: Any) -> str:
        """Resolve enum storage width from il2cpp metadata or schema size."""
        original_type = getattr(field, "original_type", "")
        if isinstance(original_type, str):
            for candidate in self._enum_type_candidates_for_lookup(original_type):
                storage_type = self.enum_underlying_types.get(candidate)
                if storage_type is not None:
                    return storage_type
        return enum_storage_type_from_size(int(getattr(field, "size", 0) or 0))

    def _apply_schema_enum_context(self) -> None:
        """Register ordinary schema Enum fields as enum-formatting hints."""
        typedb = getattr(self, "typedb", None)
        enum_lookup = getattr(self, "enum_lookup", None)
        if typedb is None or not enum_lookup:
            return

        for class_def in typedb.classes.values():
            field_map = self.class_field_fixed_types.setdefault(class_def.name, {})
            for field in class_def.fields:
                if field.field_type != "Enum":
                    continue
                enum_type = self._resolve_enum_type_for_lookup(field.original_type)
                if enum_type is not None:
                    field_map.setdefault(field.name or "unnamed", enum_type)
            if not field_map:
                self.class_field_fixed_types.pop(class_def.name, None)

    def _load_enum_context_from_il2cpp_dump(self) -> bool:
        """Load enum context from il2cpp dump.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            bool: True when the inspected value matches the expected schema or metadata pattern; otherwise False.
        """
        pending_context = getattr(self, "_pending_enum_context", None)
        if isinstance(pending_context, dict):
            self._apply_enum_context(pending_context)
            self._apply_schema_enum_context()
            self._pending_enum_context = None
            return True

        dump_path = self._resolve_il2cpp_dump_path()
        if dump_path is None:
            return False
        try:
            context = self.export_enum_context_from_il2cpp_dump_path(dump_path)
        except Exception:
            return False
        self._apply_enum_context(context)
        self._apply_schema_enum_context()
        return True

    def _ensure_enum_lookup(self) -> None:
        """Ensure enum lookup.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        if self.enum_lookup:
            self._apply_schema_enum_context()
            self._rebuild_enum_member_index()
            return
        self._rebuild_enum_member_index()
        if not self.enum_lookup:
            get_console().log(
                "[warn] enum value formatting disabled "
                f"(source: {self._resolve_il2cpp_dump_path() or 'not found'})",
                style="yellow",
            )
        if not self.class_field_fixed_types and not self.serializable_to_fixed:
            context_source = str(self._resolve_il2cpp_dump_path() or "not found")
            get_console().log(
                "[warn] Enum context not loaded, enum conversion may be incomplete "
                f"(source: {context_source})",
                style="yellow",
            )
