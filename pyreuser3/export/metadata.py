"""Metadata loading helpers for schema and il2cpp dump context."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core import ParseError
from ..rich_ui import get_console


class ExporterMetadataMixin:
    """Mixin for loading export metadata and enum context."""

    @staticmethod
    def _id_formatter(key: str, value: int) -> str:
        """Internal helper for id formatter."""
        return f"[{value}] {key}"

    @staticmethod
    def _to_u32(value: int) -> int:
        """Internal helper for to u32."""
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """Internal helper for to s32."""
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000

    def _build_enum_lookup_from_enums_internal(
        self, raw: Any
    ) -> dict[str, dict[int, tuple[str, int]]]:
        """Internal helper for build enum lookup from enums internal."""
        lookup: dict[str, dict[int, tuple[str, int]]] = {}
        if not isinstance(raw, dict):
            return lookup

        for enum_type, members in raw.items():
            if (
                not isinstance(enum_type, str)
                or not isinstance(members, dict)
                or not enum_type.endswith("_Fixed")
            ):
                continue
            value_map: dict[int, tuple[str, int]] = {}
            for member_name, raw_value in members.items():
                if not isinstance(member_name, str) or not isinstance(raw_value, int):
                    continue
                entry = (member_name, raw_value)
                # Keep the JSON shape stable for callers and editors.
                # Keep enum metadata consistent while converting values.
                value_map[self._to_s32(raw_value)] = entry
                value_map[self._to_u32(raw_value)] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """Internal helper for load enum lookup."""
        return {}

    def _resolve_il2cpp_dump_path(self) -> Path | None:
        """Internal helper for resolve il2cpp dump path."""
        return self.il2cpp_dump_path if self.il2cpp_dump_path.is_file() else None

    def _ensure_internal_metadata_files(self) -> dict:
        """Internal helper for ensure internal metadata files."""
        dump_path = self._resolve_il2cpp_dump_path()
        if dump_path is None:
            raise FileNotFoundError(
                f"il2cpp_dump.json not found: {self.il2cpp_dump_path}"
            )
        try:
            with dump_path.open("r", encoding="utf-8") as f:
                il2cpp_dump = json.load(f)
        except Exception as exc:
            raise ParseError(f"failed to read il2cpp dump: {dump_path}") from exc

        self.output_root.mkdir(parents=True, exist_ok=True)
        enums_out = self.output_root / "Enums_Internal.json"
        enums_internal = self.export_enums_internal(il2cpp_dump)
        # Keep enum metadata consistent while converting values.
        with enums_out.open("w", encoding="utf-8") as f:
            json.dump(enums_internal, f, ensure_ascii=False, indent=2)
        return enums_internal

    def _rebuild_enum_member_index(self) -> None:
        """Internal helper for rebuild enum member index."""
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
        """Internal helper for infer enum type from member and value."""
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
        # Keep enum metadata consistent while converting values.
        return None

    def _apply_enum_context(self, raw: dict) -> None:
        """Internal helper for apply enum context."""
        self.class_field_fixed_types = {}
        self.serializable_to_fixed = {}
        self.generic_container_rules = {}
        self.param_type_default_enum = {}

        class_field_fixed_types = raw.get("class_field_fixed_types")
        if isinstance(class_field_fixed_types, dict):
            for cls_name, field_map in class_field_fixed_types.items():
                if not isinstance(cls_name, str) or not isinstance(field_map, dict):
                    continue
                cleaned: dict[str, str] = {}
                for field_name, enum_type in field_map.items():
                    # Keep enum metadata consistent while converting values.
                    if (
                        isinstance(field_name, str)
                        and isinstance(enum_type, str)
                        and enum_type.endswith("_Fixed")
                    ):
                        cleaned[field_name] = enum_type
                if cleaned:
                    self.class_field_fixed_types[cls_name] = cleaned

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
        # Keep enum metadata consistent while converting values.
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
                # Keep enum metadata consistent while converting values.
                self.param_type_default_enum[param_type] = next(iter(enum_types))

    def _load_enum_context_from_il2cpp_dump(self) -> bool:
        """Internal helper for load enum context from il2cpp dump."""
        dump_path = self._resolve_il2cpp_dump_path()
        if dump_path is None:
            return False
        try:
            with dump_path.open("r", encoding="utf-8") as f:
                il2cpp_dump = json.load(f)
        except Exception:
            return False
        context = self.export_enum_context_internal(il2cpp_dump)
        self._apply_enum_context(context)
        return True

    def _ensure_enum_lookup(self) -> None:
        """Internal helper for ensure enum lookup."""
        if self.enum_lookup:
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
