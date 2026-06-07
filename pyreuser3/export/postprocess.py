"""Post-processing helpers that make exported JSON easier to edit."""

from __future__ import annotations

from typing import Any


class ExporterPostprocessMixin:
    """Mixin for cleaning and annotating exported JSON values."""

    def _fixed_type_candidates(self, type_name: str) -> list[str]:
        """Internal helper for fixed type candidates."""
        candidates = [type_name]
        if type_name.endswith("_Serializable"):
            candidates.append(f"{type_name[:-13]}_Fixed")
        if "Serializable" in type_name:
            candidates.append(type_name.replace("Serializable", "Fixed"))
        out: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                out.append(candidate)
        return out

    def _normalize_to_fixed_enum_type(self, type_name: str) -> str:
        """Internal helper for normalize to fixed enum type."""
        if not type_name or not self.enum_lookup:
            return type_name
        direct = self.serializable_to_fixed.get(type_name)
        if direct is not None and direct in self.enum_lookup:
            return direct
        for candidate in self._fixed_type_candidates(type_name):
            if candidate in self.enum_lookup:
                return candidate
        return type_name

    def _format_enum_value(self, fixed_enum_type: str, value: int) -> Any:
        """Internal helper for format enum value."""
        if not fixed_enum_type or not self.enum_lookup:
            return value
        value_map = self.enum_lookup.get(fixed_enum_type)
        if value_map is None:
            return value
        # Keep this implementation detail explicit.
        matched = value_map.get(value)
        if matched is None:
            matched = value_map.get(self._to_s32(value))
        if matched is None:
            matched = value_map.get(self._to_u32(value))
        if matched is None:
            return value
        member_name, fixed_value = matched
        return self._id_formatter(member_name, fixed_value)

    @staticmethod
    def _looks_like_class_name(text: str) -> bool:
        """Internal helper for looks like class name."""
        return "." in text and not text.startswith("_")

    @staticmethod
    def _class_name_variants(class_name: str | None) -> list[str]:
        """Internal helper for class name variants."""
        if not class_name:
            return []
        variants = [class_name]
        if class_name.endswith(".cData"):
            variants.append(f"{class_name[:-6]}.cParam")
        elif class_name.endswith(".cParam"):
            variants.append(f"{class_name[:-7]}.cData")
        return variants

    def _resolve_field_enum_hint(
        self, current_class: str | None, field_name: str
    ) -> str | None:
        """Internal helper for resolve field enum hint."""
        for class_variant in self._class_name_variants(current_class):
            class_fields = self.class_field_fixed_types.get(class_variant, {})
            fixed_field_type = class_fields.get(field_name)
            if fixed_field_type:
                return fixed_field_type
        return None

    def _resolve_class_default_enum(self, class_name: str | None) -> str | None:
        """Internal helper for resolve class default enum."""
        for class_variant in self._class_name_variants(class_name):
            enum_type = self.param_type_default_enum.get(class_variant)
            if enum_type is not None:
                return enum_type
        return None

    @staticmethod
    def _is_enum_value_field(field_name: str | None) -> bool:
        """Internal helper for is enum value field."""
        if not field_name:
            return False
        key = field_name.strip("_").lower()
        return key in {"value", "enumvalue", "fixedid"} or key.endswith("id")

    def _postprocess_enum_nodes(
        self,
        value: Any,
        current_class: str | None = None,
        scalar_enum_hint: str | None = None,
        class_default_enum: str | None = None,
        container_param_rule: tuple[str, str] | None = None,
        field_name: str | None = None,
    ) -> Any:
        """Internal helper for postprocess enum nodes."""
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            dict_level_enum_hint: str | None = None
            enum_name = value.get("_EnumName")
            fixed_id = value.get("_FixedID")
            if isinstance(enum_name, str) and isinstance(fixed_id, int):
                # Keep enum metadata consistent while converting values.
                # Keep enum metadata consistent while converting values.
                dict_level_enum_hint = self._infer_enum_type_from_member_and_value(
                    enum_name, fixed_id
                )
            for k, v in value.items():
                if (
                    isinstance(k, str)
                    and self._looks_like_class_name(k)
                    and isinstance(v, dict)
                ):
                    # Keep the JSON shape stable for callers and editors.
                    normalized_class = self._normalize_to_fixed_enum_type(k)
                    key_out = (
                        normalized_class
                        if normalized_class != k and k.endswith("_Serializable")
                        else k
                    )
                    next_scalar_hint = (
                        normalized_class
                        if normalized_class in self.enum_lookup
                        else None
                    )
                    next_container_rule = self.generic_container_rules.get(k)
                    if next_container_rule is None:
                        next_container_rule = self.generic_container_rules.get(
                            normalized_class
                        )
                    next_default_enum = self._resolve_class_default_enum(
                        normalized_class
                    )
                    if (
                        container_param_rule is not None
                        and normalized_class == container_param_rule[0]
                    ):
                        # Keep enum metadata consistent while converting values.
                        next_default_enum = container_param_rule[1]

                    out[key_out] = self._postprocess_enum_nodes(
                        v,
                        current_class=normalized_class,
                        scalar_enum_hint=next_scalar_hint,
                        class_default_enum=next_default_enum,
                        container_param_rule=next_container_rule,
                        field_name=None,
                    )
                    continue

                field_hint: str | None = None
                if current_class is not None:
                    # Keep enum metadata consistent while converting values.
                    fixed_field_type = (
                        self._resolve_field_enum_hint(current_class, k)
                        if isinstance(k, str)
                        else None
                    )
                    if fixed_field_type:
                        field_hint = fixed_field_type
                if (
                    field_hint is None
                    and class_default_enum is not None
                    and isinstance(k, str)
                    and self._is_enum_value_field(k)
                ):
                    # Keep enum metadata consistent while converting values.
                    field_hint = class_default_enum
                if (
                    field_hint is None
                    and scalar_enum_hint is not None
                    and isinstance(k, str)
                    and self._is_enum_value_field(k)
                ):
                    # Keep enum metadata consistent while converting values.
                    field_hint = scalar_enum_hint
                if (
                    field_hint is None
                    and dict_level_enum_hint is not None
                    and isinstance(k, str)
                    and k.strip("_").lower() == "fixedid"
                ):
                    # Keep enum metadata consistent while converting values.
                    field_hint = dict_level_enum_hint

                out[k] = self._postprocess_enum_nodes(
                    v,
                    current_class=current_class,
                    scalar_enum_hint=field_hint,
                    class_default_enum=class_default_enum,
                    container_param_rule=container_param_rule,
                    field_name=k if isinstance(k, str) else None,
                )
            return out

        if isinstance(value, list):
            # Keep this implementation detail explicit.
            return [
                self._postprocess_enum_nodes(
                    item,
                    current_class=current_class,
                    scalar_enum_hint=scalar_enum_hint,
                    class_default_enum=class_default_enum,
                    container_param_rule=container_param_rule,
                    field_name=field_name,
                )
                for item in value
            ]
        if isinstance(value, int) and scalar_enum_hint is not None:
            # Keep enum metadata consistent while converting values.
            return self._format_enum_value(scalar_enum_hint, value)
        return value

    def _finalize_export_tree(self, value: Any) -> Any:
        """Internal helper for finalize export tree."""
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k == "index":
                    # Keep this implementation detail explicit.
                    continue
                out[k] = self._finalize_export_tree(v)
            if len(out) == 1:
                only_key = next(iter(out))
                if only_key == "value":
                    return out[only_key]
                if isinstance(only_key, str) and only_key in self.enum_lookup:
                    return out[only_key]
            return out
        if isinstance(value, list):
            return [self._finalize_export_tree(item) for item in value]
        return value

    def _round_export_floats(self, value: Any) -> Any:
        """Internal helper for round export floats."""
        if isinstance(value, dict):
            return {k: self._round_export_floats(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._round_export_floats(item) for item in value]
        if isinstance(value, float):
            return round(value, 4)
        return value
