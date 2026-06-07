"""Build compact object trees from flat RSZ instance tables.

The tree builder follows object references from root instances, detects cycles, keeps
unresolved references explicit, and automatically reduces depth for very dense files.
"""

from __future__ import annotations

from typing import Any


class ExporterTreeMixin:
    """Resolve flat RSZ instance references into compact JSON object trees while preserving
    unresolved links.
    """

    def _count_reference_links(self, value: Any) -> int:
        """Count reference links.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                return 1
            total = 0
            for child in value.values():
                total += self._count_reference_links(child)
            return total
        if isinstance(value, list):
            return sum(self._count_reference_links(child) for child in value)
        return 0

    def _collect_reference_ids(self, value: Any, out: set[int]) -> None:
        """Collect reference ids.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            out (set[int]): Mutable collection being populated by the recursive helper.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                out.add(value["ref_instance_id"])
                return
            for child in value.values():
                self._collect_reference_ids(child, out)
            return
        if isinstance(value, list):
            for child in value:
                self._collect_reference_ids(child, out)

    def _infer_roots_when_object_table_empty(
        self,
        idx_map: dict[int, dict[str, Any]],
        parsed_instances: list[dict[str, Any]],
    ) -> list[int]:
        """Infer roots when object table empty.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            idx_map (dict[int, dict[str, Any]]): Mapping used to resolve related metadata.
            parsed_instances (list[dict[str, Any]]): Parsed RSZ instance table used for reference-tree construction.

        Returns:
            list[int]: Instance indexes collected from roots, references, or normalized JSON input.
        """
        candidates = sorted(
            idx
            for idx, inst in idx_map.items()
            if idx > 0 and isinstance(inst.get("data", {}).get("fields"), dict)
        )
        if not candidates:
            return []

        referenced: set[int] = set()
        for inst in parsed_instances:
            fields = inst.get("data", {}).get("fields")
            if isinstance(fields, dict):
                # Preserve instance numbering and reference identity; RSZ object links
                # depend on these indexes remaining stable.
                self._collect_reference_ids(fields, referenced)

        inferred = [idx for idx in candidates if idx not in referenced]
        if inferred:
            return inferred
        return candidates

    def _auto_pick_tree_depth(
        self, parsed_instances: list[dict[str, Any]], object_roots: list[int]
    ) -> int:
        """Choose automatically pick tree depth.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            parsed_instances (list[dict[str, Any]]): Parsed RSZ instance table used for reference-tree construction.
            object_roots (list[int]): Instance indexes that are reachable from the object-info table.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        ref_links = 0
        for inst in parsed_instances:
            fields = inst.get("data", {}).get("fields")
            if isinstance(fields, dict):
                ref_links += self._count_reference_links(fields)

        # Preserve instance numbering and reference identity; RSZ object links depend on
        # these indexes remaining stable.
        complexity = max(len(parsed_instances), ref_links, len(object_roots) * 10)
        if complexity <= 1500:
            return 4
        if complexity <= 8000:
            return 3
        if complexity <= 30000:
            return 2
        return 1

    def _simplify_value_object(self, value: Any) -> Any:
        """Simplify value object.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if isinstance(value, dict) and len(value) == 1 and "_Value" in value:
            return value["_Value"]
        return value

    def _resolve_compact_value(
        self,
        value: Any,
        idx_map: dict[int, dict[str, Any]],
        depth: int,
        visited: set[int],
    ) -> Any:
        """Resolve compact value.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            idx_map (dict[int, dict[str, Any]]): Mapping used to resolve related metadata.
            depth (int): Remaining recursive expansion depth for reference traversal.
            visited (set[int]): Set of instance indexes already seen on the current traversal path.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                target_idx = value["ref_instance_id"]
                if depth <= 0:
                    return {"ref_instance_id": target_idx}
                # Keep a reference instead of expanding the target again to prevent
                # infinite recursion in cyclic object graphs.
                return self._build_compact_tree(
                    target_idx, idx_map, depth - 1, set(visited)
                )
            out: dict[str, Any] = {}
            for k, v in value.items():
                out[k] = self._resolve_compact_value(v, idx_map, depth, set(visited))
            return out
        if isinstance(value, list):
            return [
                self._resolve_compact_value(v, idx_map, depth, set(visited))
                for v in value
            ]
        return value

    def _build_compact_tree(
        self,
        idx: int,
        idx_map: dict[int, dict[str, Any]],
        depth: int,
        instance_info_map: dict[int, dict[str, Any]] | None = None,
        visited: set[int] | None = None,
    ) -> dict[str, Any]:
        """Build compact tree.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            idx (int): RSZ instance index being parsed, planned, or written.
            idx_map (dict[int, dict[str, Any]]): Mapping used to resolve related metadata.
            depth (int): Remaining recursive expansion depth for reference traversal.
            instance_info_map (dict[int, dict[str, Any]] | None): Mapping used to resolve
            related metadata.
            visited (set[int] | None): Set of instance indexes already seen on the current traversal path.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.
        """
        if visited is None:
            visited = set()
        if idx in visited:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            return {"Ref": {"ref_instance_id": idx, "cycle": True}}
        visited.add(idx)

        inst = idx_map.get(idx)
        if inst is None:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            if instance_info_map is not None and idx in instance_info_map:
                class_name = instance_info_map[idx].get("class_name", "Unknown Class")
                class_name = self._normalize_to_fixed_enum_type(class_name)
                return {class_name: {"ref_instance_id": idx, "unparsed": True}}
            return {"Ref": {"ref_instance_id": idx, "missing": True}}

        if inst.get("is_userdata_reference"):
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            # Resolve and validate paths at the boundary so later code never guesses
            # relative to a surprising working directory.
            class_name = inst.get("class_name", "Unknown Class")
            class_name = self._normalize_to_fixed_enum_type(class_name)
            return {
                class_name: {
                    "ref_instance_id": idx,
                    "path": inst.get("path", ""),
                }
            }

        data = inst.get("data", {})
        class_name = data.get("_class", inst.get("class_name", "Unknown Class"))
        class_name = self._normalize_to_fixed_enum_type(class_name)
        fields = data.get("fields", {})
        if not isinstance(fields, dict):
            fields = {}

        resolved = self._resolve_compact_value_with_info(
            fields, idx_map, depth, instance_info_map, visited
        )
        resolved = self._simplify_value_object(resolved)

        if isinstance(resolved, dict):
            node_value: Any = resolved
        else:
            # Wrap scalar or non-dict results in a value field so every tree node keeps a consistent object shape.
            node_value = {"value": resolved}

        return {class_name: node_value}

    def _resolve_compact_value_with_info(
        self,
        value: Any,
        idx_map: dict[int, dict[str, Any]],
        depth: int,
        instance_info_map: dict[int, dict[str, Any]] | None,
        visited: set[int],
    ) -> Any:
        """Resolve compact value with info.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            idx_map (dict[int, dict[str, Any]]): Mapping used to resolve related metadata.
            depth (int): Remaining recursive expansion depth for reference traversal.
            instance_info_map (dict[int, dict[str, Any]] | None): Mapping used to resolve
            related metadata.
            visited (set[int]): Set of instance indexes already seen on the current traversal path.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                target_idx = value["ref_instance_id"]
                if depth <= 0:
                    return {"ref_instance_id": target_idx}
                return self._build_compact_tree(
                    target_idx,
                    idx_map,
                    depth - 1,
                    instance_info_map=instance_info_map,
                    visited=set(visited),
                )
            out: dict[str, Any] = {}
            for k, v in value.items():
                out[k] = self._resolve_compact_value_with_info(
                    v, idx_map, depth, instance_info_map, set(visited)
                )
            return out
        if isinstance(value, list):
            return [
                self._resolve_compact_value_with_info(
                    v, idx_map, depth, instance_info_map, set(visited)
                )
                for v in value
            ]
        return value
