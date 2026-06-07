"""Extract enum tables from REFramework il2cpp dumps.

The exported metadata is used to replace fixed enum integer values with readable labels
and to rebuild numeric values when packing.
"""

from __future__ import annotations

import re
from typing import Any

from ..core import ENUM_UNUSED_KEY


class ExporterEnumSourceMixin:
    """Extract enum member tables from il2cpp dump data and normalize them into exporter
    metadata.
    """

    @staticmethod
    def export_enums_internal(dump_json: dict) -> dict:
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
            if isinstance(value, dict):
                obj = dump_json[key]
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                if "parent" in obj and obj["parent"] == "System.Enum":
                    val = {}
                    for _k, _v in obj["fields"].items():
                        # Register enum values through the shared lookup tables so
                        # readable labels and numeric packing stay reversible.
                        if _k != ENUM_UNUSED_KEY:
                            val[_k] = _v["default"]
                    enums_internal[key] = val
        return enums_internal

    @staticmethod
    def export_enum_context_internal(dump_json: dict) -> dict:
        """Export enum context internal.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            dump_json (dict): Parsed il2cpp_dump.json content used to build enum maps.

        Returns:
            dict: Mapping populated from schema, enum, or job metadata.
        """

        def extract_fixed_enum_type(type_name: Any) -> str | None:
            """Extract fixed enum type.

            The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
            templates can still produce inspectable output.

            Args:
                type_name (Any): Schema or il2cpp type name being normalized or searched.

            Returns:
                str | None: Resolved string when a match is available; otherwise None.
            """
            if not isinstance(type_name, str):
                return None
            matches = re.findall(r"[A-Za-z0-9_.]+_Fixed", type_name)
            if not matches:
                return None
            # Register enum values through the shared lookup tables so readable labels
            # and numeric packing stay reversible.
            unique = list(dict.fromkeys(matches))
            if len(unique) == 1:
                return unique[0]
            return None

        class_field_fixed_types: dict[str, dict[str, str]] = {}
        serializable_to_fixed: dict[str, str] = {}
        generic_container_rules: dict[str, dict[str, str]] = {}

        for class_name, obj in dump_json.items():
            if not isinstance(class_name, str) or not isinstance(obj, dict):
                continue

            field_map: dict[str, str] = {}
            fields_obj = obj.get("fields")
            if isinstance(fields_obj, dict):
                for field_name, field_info in fields_obj.items():
                    if not isinstance(field_name, str) or not isinstance(
                        field_info, dict
                    ):
                        continue
                    fixed_type = extract_fixed_enum_type(field_info.get("type"))
                    if fixed_type is not None:
                        field_map[field_name] = fixed_type

            # Register enum values through the shared lookup tables so readable labels
            # and numeric packing stay reversible.
            rsz_fields = obj.get("RSZ")
            if isinstance(rsz_fields, list):
                for rsz_field in rsz_fields:
                    if not isinstance(rsz_field, dict):
                        continue
                    potential_name = rsz_field.get("potential_name")
                    fixed_type = extract_fixed_enum_type(rsz_field.get("type"))
                    if isinstance(potential_name, str) and fixed_type is not None:
                        field_map.setdefault(potential_name, fixed_type)

            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            reflection_props = obj.get("reflection_properties")
            if isinstance(reflection_props, dict):
                for prop_name, prop_info in reflection_props.items():
                    if not isinstance(prop_name, str) or not isinstance(
                        prop_info, dict
                    ):
                        continue
                    fixed_type = extract_fixed_enum_type(prop_info.get("type"))
                    if fixed_type is not None:
                        field_map.setdefault(prop_name, fixed_type)

            if field_map:
                class_field_fixed_types[class_name] = field_map

            if class_name.endswith("_Serializable"):
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                fixed_types: set[str] = set()
                methods_obj = obj.get("methods")
                if isinstance(methods_obj, dict):
                    for method in methods_obj.values():
                        if not isinstance(method, dict):
                            continue
                        params = method.get("params")
                        if isinstance(params, list):
                            for param in params:
                                if not isinstance(param, dict):
                                    continue
                                fixed_type = extract_fixed_enum_type(param.get("type"))
                                if fixed_type is not None:
                                    fixed_types.add(fixed_type)
                        returns = method.get("returns")
                        if isinstance(returns, dict):
                            fixed_type = extract_fixed_enum_type(returns.get("type"))
                            if fixed_type is not None:
                                fixed_types.add(fixed_type)
                if len(fixed_types) == 1:
                    serializable_to_fixed[class_name] = next(iter(fixed_types))

            generic_args = obj.get("generic_arg_types")
            if isinstance(generic_args, list) and len(generic_args) >= 2:
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                enum_arg = generic_args[0]
                param_arg = generic_args[1]
                enum_type = (
                    extract_fixed_enum_type(enum_arg.get("type"))
                    if isinstance(enum_arg, dict)
                    else None
                )
                param_type = (
                    param_arg.get("type") if isinstance(param_arg, dict) else None
                )
                if isinstance(enum_type, str) and isinstance(param_type, str):
                    generic_container_rules[class_name] = {
                        "param_type": param_type,
                        "enum_type": enum_type,
                    }

        return {
            "class_field_fixed_types": class_field_fixed_types,
            "serializable_to_fixed": serializable_to_fixed,
            "generic_container_rules": generic_container_rules,
        }
