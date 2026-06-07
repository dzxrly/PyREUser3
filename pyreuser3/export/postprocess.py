"""Normalize class names, resolve enum labels, remove internal parser indexes, and round floats after raw parsing.

These transformations keep exported JSON readable while preserving enough structure for
later packing.
"""

from __future__ import annotations

from typing import Any


class ExporterPostprocessMixin:
    """Clean parsed JSON trees by normalizing enum labels, class names, indexes, wrappers, and
    floats.
    """

    def _fixed_type_candidates(self, type_name: str) -> list[str]:
        """Yield possible metadata keys for a fixed or partially qualified enum type name.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            type_name (str): Schema or il2cpp type name being normalized or searched.

        Returns:
            list[str]: Normalized string candidates or exclusion patterns.
        """
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
        """Normalize to fixed enum type.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            type_name (str): Schema or il2cpp type name being normalized or searched.

        Returns:
            str: Normalized or formatted text.
        """
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
        """Format enum value.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            fixed_enum_type (str): Resolved enum type used to interpret a fixed-size numeric field.
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if not fixed_enum_type or not self.enum_lookup:
            return value
        value_map = self.enum_lookup.get(fixed_enum_type)
        if value_map is None:
            return value
        # Leave numeric enum values unchanged when no enum lookup is available for the current context.
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
        """Return whether a type name appears to reference a managed class.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            text (str): Text to normalize or parse.

        Returns:
            bool: True when the inspected value matches the expected schema or metadata pattern; otherwise False.
        """
        return "." in text and not text.startswith("_")

    @staticmethod
    def _class_name_variants(class_name: str | None) -> list[str]:
        """Yield class-name lookup variants that account for namespaces and nested types.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            class_name (str | None): Fully qualified RE_RSZ class name.

        Returns:
            list[str]: Normalized string candidates or exclusion patterns.
        """
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
        """Resolve field enum hint.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            current_class (str | None): Current class context used for enum hint resolution.
            field_name (str): Name of the current schema or JSON field.

        Returns:
            str | None: Resolved string when a match is available; otherwise None.
        """
        for class_variant in self._class_name_variants(current_class):
            class_fields = self.class_field_fixed_types.get(class_variant, {})
            fixed_field_type = class_fields.get(field_name)
            if fixed_field_type:
                return fixed_field_type
        return None

    def _resolve_class_default_enum(self, class_name: str | None) -> str | None:
        """Resolve class default enum.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            class_name (str | None): Fully qualified RE_RSZ class name.

        Returns:
            str | None: Resolved string when a match is available; otherwise None.
        """
        for class_variant in self._class_name_variants(class_name):
            enum_type = self.param_type_default_enum.get(class_variant)
            if enum_type is not None:
                return enum_type
        return None

    @staticmethod
    def _is_enum_value_field(field_name: str | None) -> bool:
        """Return whether the input is enum value field.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            field_name (str | None): Name of the current schema or JSON field.

        Returns:
            bool: True when the inspected value matches the expected schema or metadata pattern; otherwise False.
        """
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
        """Walk an exported JSON tree and replace numeric enum fields with readable labels.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            current_class (str | None): Current class context used for enum hint resolution.
            scalar_enum_hint (str | None): Optional enum hint inherited from the
            surrounding scalar field context.
            class_default_enum (str | None): Default enum type inferred from the
            current class or field context.
            container_param_rule (tuple[str, str] | None): Container
            generic-parameter rule used to infer enum context inside arrays or lists.
            field_name (str | None): Name of the current schema or JSON field.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            dict_level_enum_hint: str | None = None
            enum_name = value.get("_EnumName")
            fixed_id = value.get("_FixedID")
            if isinstance(enum_name, str) and isinstance(fixed_id, int):
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                dict_level_enum_hint = self._infer_enum_type_from_member_and_value(
                    enum_name, fixed_id
                )
            for k, v in value.items():
                if (
                    isinstance(k, str)
                    and self._looks_like_class_name(k)
                    and isinstance(v, dict)
                ):
                    # Preserve the exported JSON structure so external scripts and hand-
                    # edited files remain compatible across workflows.
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
                        # Register enum values through the shared lookup tables so
                        # readable labels and numeric packing stay reversible.
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
                    # Register enum values through the shared lookup tables so readable
                    # labels and numeric packing stay reversible.
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
                    # Register enum values through the shared lookup tables so readable
                    # labels and numeric packing stay reversible.
                    field_hint = class_default_enum
                if (
                    field_hint is None
                    and scalar_enum_hint is not None
                    and isinstance(k, str)
                    and self._is_enum_value_field(k)
                ):
                    # Register enum values through the shared lookup tables so readable
                    # labels and numeric packing stay reversible.
                    field_hint = scalar_enum_hint
                if (
                    field_hint is None
                    and dict_level_enum_hint is not None
                    and isinstance(k, str)
                    and k.strip("_").lower() == "fixedid"
                ):
                    # Register enum values through the shared lookup tables so readable
                    # labels and numeric packing stay reversible.
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
            # Lists inherit the current enum context for each element because RE
            # Engine arrays share one declared field type.
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
            # Register enum values through the shared lookup tables so readable labels
            # and numeric packing stay reversible.
            return self._format_enum_value(scalar_enum_hint, value)
        return value

    def _finalize_export_tree(self, value: Any) -> Any:
        """Remove parser-only fields and produce the final editable export tree.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if k == "index":
                    # Drop parser-only index fields from exported JSON; instance
                    # ordering is represented by surrounding arrays and references.
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
        """Round exported floating-point values for stable and readable JSON output.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if isinstance(value, dict):
            return {k: self._round_export_floats(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._round_export_floats(item) for item in value]
        if isinstance(value, float):
            return round(value, 4)
        return value
