"""Extract enum tables from REFramework il2cpp dumps.

The exported metadata is used to replace fixed enum integer values with readable labels
and to rebuild numeric values when packing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..core import ENUM_UNUSED_KEY, normalize_enum_storage_type


_FIXED_ENUM_RE = re.compile(r"[A-Za-z0-9_.+]+_Fixed")
_PROPERTY_METHOD_RE = re.compile(r"^(?:get|set)_(?P<name>.+?)(?:\d+)?$")
_BACKING_FIELD_RE = re.compile(r"^<(?P<name>[^>]+)>")


class ExporterEnumSourceMixin:
    """Extract enum member tables from il2cpp dump data and normalize them into exporter
    metadata.
    """

    @staticmethod
    def _parse_enum_default(value: Any) -> int | None:
        """Return an integer enum value from il2cpp field metadata."""
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return int(text, 0)
            except ValueError:
                return None
        return None

    @staticmethod
    def _extract_enum_underlying_type(obj: Any) -> str | None:
        """Extract a normalized enum storage type from ``fields.value__`` metadata."""
        if not isinstance(obj, dict):
            return None
        fields_obj = obj.get("fields")
        if isinstance(fields_obj, dict):
            value_field = fields_obj.get(ENUM_UNUSED_KEY)
            if isinstance(value_field, dict):
                storage_type = normalize_enum_storage_type(value_field.get("type"))
                if storage_type is not None:
                    return storage_type
        reflection_props = obj.get("reflection_properties")
        if isinstance(reflection_props, dict):
            value_prop = reflection_props.get(ENUM_UNUSED_KEY)
            if isinstance(value_prop, dict):
                return normalize_enum_storage_type(value_prop.get("type"))
        return None

    @staticmethod
    def _extract_fixed_enum_type(type_name: Any) -> str | None:
        """Extract one unambiguous ``*_Fixed`` enum type from a metadata type string."""
        if not isinstance(type_name, str):
            return None
        matches = _FIXED_ENUM_RE.findall(type_name)
        if not matches:
            return None
        unique = list(dict.fromkeys(matches))
        if len(unique) == 1:
            return unique[0]
        return None

    @staticmethod
    def _field_name_variants(field_name: str) -> list[str]:
        """Return schema and reflection name variants for one il2cpp field name."""
        out = [field_name]
        match = _BACKING_FIELD_RE.match(field_name)
        if match:
            out.append(match.group("name"))
        return list(dict.fromkeys(out))

    @staticmethod
    def _property_name_from_method(method_name: str) -> str | None:
        """Infer a property name from generated getter/setter method names."""
        match = _PROPERTY_METHOD_RE.match(method_name)
        if match:
            return match.group("name")
        return None

    @classmethod
    def _add_field_fixed_type(
        cls, field_map: dict[str, str], field_name: Any, type_name: Any
    ) -> None:
        """Record a field-to-fixed-enum hint when both sides are valid."""
        if not isinstance(field_name, str):
            return
        fixed_type = cls._extract_fixed_enum_type(type_name)
        if fixed_type is None:
            return
        for candidate in cls._field_name_variants(field_name):
            field_map.setdefault(candidate, fixed_type)

    @staticmethod
    def _method_matches_property(method_name: str, getter_or_setter: str) -> bool:
        """Return whether an il2cpp method key represents the named property accessor."""
        if method_name == getter_or_setter:
            return True
        if not method_name.startswith(getter_or_setter):
            return False
        suffix = method_name[len(getter_or_setter) :]
        return suffix.isdigit()

    @classmethod
    def _fixed_type_from_method_return(cls, method: Any) -> str | None:
        if not isinstance(method, dict):
            return None
        returns = method.get("returns")
        if isinstance(returns, dict):
            return cls._extract_fixed_enum_type(returns.get("type"))
        return None

    @classmethod
    def _fixed_type_from_method_params(cls, method: Any) -> str | None:
        if not isinstance(method, dict):
            return None
        params = method.get("params")
        if not isinstance(params, list):
            return None
        fixed_types: list[str] = []
        for param in params:
            if not isinstance(param, dict):
                continue
            fixed_type = cls._extract_fixed_enum_type(param.get("type"))
            if fixed_type is not None:
                fixed_types.append(fixed_type)
        unique = list(dict.fromkeys(fixed_types))
        if len(unique) == 1:
            return unique[0]
        return None

    @classmethod
    def _enum_type_name_fallbacks(
        cls, class_name: str, enum_types: set[str]
    ) -> list[str]:
        """Return likely fixed-enum names inferred from a serializable class name."""
        candidates: list[str] = []
        if class_name.endswith("_Serializable"):
            candidates.append(f"{class_name[:-13]}_Fixed")
        if "Serializable" in class_name:
            candidates.append(class_name.replace("Serializable", "Fixed"))
        return list(
            dict.fromkeys(
                candidate for candidate in candidates if candidate in enum_types
            )
        )

    @staticmethod
    def _iter_il2cpp_dump_items(dump_path: str | Path) -> Iterator[tuple[str, Any]]:
        """Yield top-level ``il2cpp_dump.json`` entries without loading the whole file."""
        decoder = json.JSONDecoder()
        path = Path(dump_path)
        buffer = ""
        pos = 0
        eof = False
        chunk_size = 1024 * 1024

        with path.open("r", encoding="utf-8-sig") as f:

            def read_more() -> bool:
                nonlocal buffer, eof
                chunk = f.read(chunk_size)
                if chunk:
                    buffer += chunk
                    return True
                eof = True
                return False

            def ensure_token() -> bool:
                nonlocal pos
                while True:
                    while pos < len(buffer) and buffer[pos].isspace():
                        pos += 1
                    if pos < len(buffer):
                        return True
                    if eof or not read_more():
                        return False

            def decode_at_position() -> tuple[Any, int]:
                nonlocal buffer
                while True:
                    try:
                        return decoder.raw_decode(buffer, pos)
                    except json.JSONDecodeError:
                        if eof or not read_more():
                            raise

            if not ensure_token() or buffer[pos] != "{":
                raise ValueError(f"il2cpp dump must be a JSON object: {path}")
            pos += 1

            while True:
                if not ensure_token():
                    raise ValueError(f"unexpected end of il2cpp dump: {path}")
                if buffer[pos] == "}":
                    return
                if buffer[pos] == ",":
                    pos += 1
                    continue

                key, pos = decode_at_position()
                if not isinstance(key, str):
                    raise ValueError(f"top-level il2cpp key must be a string: {path}")
                if not ensure_token() or buffer[pos] != ":":
                    raise ValueError(f"expected ':' after il2cpp key {key!r}: {path}")
                pos += 1
                if not ensure_token():
                    raise ValueError(f"unexpected end after il2cpp key {key!r}: {path}")
                value, pos = decode_at_position()
                yield key, value

                if pos > chunk_size * 8:
                    buffer = buffer[pos:]
                    pos = 0

    @classmethod
    def _add_enum_internal_entry(
        cls, enums_internal: dict, class_name: Any, obj: Any
    ) -> None:
        """Add one enum table from a top-level il2cpp class entry when possible."""
        if not isinstance(class_name, str) or not isinstance(obj, dict):
            return
        if obj.get("parent") != "System.Enum":
            return
        fields_obj = obj.get("fields")
        if not isinstance(fields_obj, dict):
            return

        values: dict[str, int] = {}
        for field_name, field_info in fields_obj.items():
            if not isinstance(field_name, str) or field_name == ENUM_UNUSED_KEY:
                continue
            if not isinstance(field_info, dict):
                continue
            default = cls._parse_enum_default(field_info.get("default"))
            if default is not None:
                values[field_name] = default
        if values:
            enums_internal[class_name] = values

    @staticmethod
    def _new_enum_context_state() -> dict[str, Any]:
        """Create mutable state used while collecting enum context entries."""
        return {
            "class_field_fixed_types": {},
            "serializable_to_fixed": {},
            "generic_container_rules": {},
            "enum_underlying_types": {},
            "enum_types": set(),
            "serializable_fallback_candidates": [],
        }

    @classmethod
    def _collect_enum_context_entry(
        cls, state: dict[str, Any], class_name: Any, obj: Any
    ) -> None:
        """Collect enum context from one top-level il2cpp class entry."""
        if not isinstance(class_name, str) or not isinstance(obj, dict):
            return

        if class_name.endswith("_Fixed") and obj.get("parent") == "System.Enum":
            state["enum_types"].add(class_name)
        if obj.get("parent") == "System.Enum":
            storage_type = cls._extract_enum_underlying_type(obj)
            if storage_type is not None:
                state["enum_underlying_types"][class_name] = storage_type

        field_map: dict[str, str] = {}
        fields_obj = obj.get("fields")
        if isinstance(fields_obj, dict):
            for field_name, field_info in fields_obj.items():
                if not isinstance(field_name, str) or not isinstance(field_info, dict):
                    continue
                cls._add_field_fixed_type(
                    field_map, field_name, field_info.get("type")
                )

        # Older dumps expose RE_RSZ field hints through an explicit RSZ array.
        rsz_fields = obj.get("RSZ")
        if isinstance(rsz_fields, list):
            for rsz_field in rsz_fields:
                if not isinstance(rsz_field, dict):
                    continue
                potential_name = rsz_field.get("potential_name")
                if not isinstance(potential_name, str):
                    potential_name = rsz_field.get("name")
                cls._add_field_fixed_type(
                    field_map, potential_name, rsz_field.get("type")
                )

        # Newer dumps can omit RSZ entirely but keep property/type hints here.
        reflection_props = obj.get("reflection_properties")
        if isinstance(reflection_props, dict):
            for prop_name, prop_info in reflection_props.items():
                if not isinstance(prop_name, str) or not isinstance(prop_info, dict):
                    continue
                cls._add_field_fixed_type(field_map, prop_name, prop_info.get("type"))

        methods_obj = obj.get("methods")
        if isinstance(methods_obj, dict):
            properties_obj = obj.get("properties")
            if isinstance(properties_obj, dict):
                for prop_name, prop_info in properties_obj.items():
                    if not isinstance(prop_name, str) or not isinstance(prop_info, dict):
                        continue
                    getter = prop_info.get("getter")
                    if isinstance(getter, str) and getter:
                        for method_name, method in methods_obj.items():
                            if not isinstance(method_name, str):
                                continue
                            if not cls._method_matches_property(method_name, getter):
                                continue
                            fixed_type = cls._fixed_type_from_method_return(method)
                            if fixed_type is not None:
                                cls._add_field_fixed_type(
                                    field_map, prop_name, fixed_type
                                )
                    setter = prop_info.get("setter")
                    if isinstance(setter, str) and setter:
                        for method_name, method in methods_obj.items():
                            if not isinstance(method_name, str):
                                continue
                            if not cls._method_matches_property(method_name, setter):
                                continue
                            fixed_type = cls._fixed_type_from_method_params(method)
                            if fixed_type is not None:
                                cls._add_field_fixed_type(
                                    field_map, prop_name, fixed_type
                                )

            for method_name, method in methods_obj.items():
                if not isinstance(method_name, str) or not isinstance(method, dict):
                    continue
                method_prop_name = cls._property_name_from_method(method_name)
                if method_prop_name is None:
                    continue
                fixed_type = None
                if method_name.startswith("get_"):
                    fixed_type = cls._fixed_type_from_method_return(method)
                elif method_name.startswith("set_"):
                    fixed_type = cls._fixed_type_from_method_params(method)
                if fixed_type is not None:
                    cls._add_field_fixed_type(field_map, method_prop_name, fixed_type)

        if field_map:
            state["class_field_fixed_types"][class_name] = field_map

        if class_name.endswith("_Serializable"):
            fixed_types: set[str] = set()
            if isinstance(methods_obj, dict):
                for method in methods_obj.values():
                    if not isinstance(method, dict):
                        continue
                    params = method.get("params")
                    if isinstance(params, list):
                        for param in params:
                            if not isinstance(param, dict):
                                continue
                            fixed_type = cls._extract_fixed_enum_type(param.get("type"))
                            if fixed_type is not None:
                                fixed_types.add(fixed_type)
                    returns = method.get("returns")
                    if isinstance(returns, dict):
                        fixed_type = cls._extract_fixed_enum_type(returns.get("type"))
                        if fixed_type is not None:
                            fixed_types.add(fixed_type)
            if len(fixed_types) == 1:
                state["serializable_to_fixed"][class_name] = next(iter(fixed_types))
            elif not fixed_types:
                state["serializable_fallback_candidates"].append(class_name)

        generic_args = obj.get("generic_arg_types")
        if isinstance(generic_args, list) and len(generic_args) >= 2:
            enum_types_in_args: list[str] = []
            param_types: list[str] = []
            for arg in generic_args:
                if not isinstance(arg, dict):
                    continue
                raw_type = arg.get("type")
                fixed_type = cls._extract_fixed_enum_type(raw_type)
                if fixed_type is not None:
                    enum_types_in_args.append(fixed_type)
                elif isinstance(raw_type, str) and raw_type != "unknown":
                    param_types.append(raw_type)
            enum_types_unique = list(dict.fromkeys(enum_types_in_args))
            param_types_unique = list(dict.fromkeys(param_types))
            if len(enum_types_unique) == 1 and len(param_types_unique) == 1:
                state["generic_container_rules"][class_name] = {
                    "param_type": param_types_unique[0],
                    "enum_type": enum_types_unique[0],
                }

    @classmethod
    def _finalize_enum_context_state(cls, state: dict[str, Any]) -> dict:
        """Finalize collected enum context after all top-level entries are seen."""
        enum_types = state["enum_types"]
        serializable_to_fixed = state["serializable_to_fixed"]
        for class_name in state["serializable_fallback_candidates"]:
            if class_name in serializable_to_fixed:
                continue
            fallback_types = cls._enum_type_name_fallbacks(class_name, enum_types)
            if len(fallback_types) == 1:
                serializable_to_fixed[class_name] = fallback_types[0]

        return {
            "class_field_fixed_types": state["class_field_fixed_types"],
            "serializable_to_fixed": serializable_to_fixed,
            "generic_container_rules": state["generic_container_rules"],
            "enum_underlying_types": state["enum_underlying_types"],
        }

    @classmethod
    def export_enums_from_il2cpp_dump_path(cls, dump_path: str | Path) -> dict:
        """Export enum tables from an il2cpp dump path using streaming top-level reads."""
        enums_internal: dict = {}
        for class_name, obj in cls._iter_il2cpp_dump_items(dump_path):
            cls._add_enum_internal_entry(enums_internal, class_name, obj)
        return enums_internal

    @classmethod
    def export_enum_context_from_il2cpp_dump_path(cls, dump_path: str | Path) -> dict:
        """Export enum context from an il2cpp dump path using streaming top-level reads."""
        state = cls._new_enum_context_state()
        for class_name, obj in cls._iter_il2cpp_dump_items(dump_path):
            cls._collect_enum_context_entry(state, class_name, obj)
        return cls._finalize_enum_context_state(state)

    @classmethod
    def export_il2cpp_metadata_from_path(cls, dump_path: str | Path) -> tuple[dict, dict]:
        """Export enum tables and enum context in one streaming pass over a dump file."""
        enums_internal: dict = {}
        state = cls._new_enum_context_state()
        for class_name, obj in cls._iter_il2cpp_dump_items(dump_path):
            cls._add_enum_internal_entry(enums_internal, class_name, obj)
            cls._collect_enum_context_entry(state, class_name, obj)
        return enums_internal, cls._finalize_enum_context_state(state)

    @classmethod
    def export_enums_internal(cls, dump_json: dict) -> dict:
        """Export enums internal.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            dump_json (dict): Parsed il2cpp_dump.json content used to build enum maps.

        Returns:
            dict: Mapping populated from schema, enum, or job metadata.
        """
        enums_internal = {}
        for key, value in dump_json.items():
            cls._add_enum_internal_entry(enums_internal, key, value)
        return enums_internal

    @classmethod
    def export_enum_context_internal(cls, dump_json: dict) -> dict:
        """Export enum context internal.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            dump_json (dict): Parsed il2cpp_dump.json content used to build enum maps.

        Returns:
            dict: Mapping populated from schema, enum, or job metadata.
        """

        state = cls._new_enum_context_state()
        for class_name, obj in dump_json.items():
            cls._collect_enum_context_entry(state, class_name, obj)
        return cls._finalize_enum_context_state(state)
