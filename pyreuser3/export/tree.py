"""`.user.3` 对象引用树构建逻辑。

RSZ 实例之间通过实例编号互相引用，扁平存放。本模块负责从根实例出发，按
给定深度把这些引用展开成嵌套 JSON 树，并处理循环引用、缺失实例、用户数据
引用以及对象表为空时的根节点推断。
"""

from __future__ import annotations

from typing import Any


class ExporterTreeMixin:
    """负责从实例表和引用关系中构造紧凑 JSON 树。"""

    def _count_reference_links(self, value: Any) -> int:
        """统计嵌套结构中的对象引用数量。

        参数：
            value (Any): 任意嵌套值（dict / list / 标量）。

        返回：
            int: ``ref_instance_id`` 出现的总次数。
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
        """收集嵌套结构中引用到的实例编号。

        参数：
            value (Any): 任意嵌套值（dict / list / 标量）。
            out (set[int]): 用于保存实例编号的输出集合，原地写入。

        返回：
            None: 结果通过 ``out`` 参数返回。
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
        """在对象表为空时推断可能的根实例。

        参数：
            idx_map (dict[int, dict[str, Any]]): 以实例编号索引的已解析实例。
            parsed_instances (list[dict[str, Any]]): 按实例表顺序排列的已解析实例列表。

        返回：
            list[int]: 推断出的根实例编号；优先返回未被任何实例引用的候选，
            否则退回所有候选。
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
                # 未被其他实例引用的候选实例通常就是根节点。
                self._collect_reference_ids(fields, referenced)

        inferred = [idx for idx in candidates if idx not in referenced]
        if inferred:
            return inferred
        return candidates

    def _auto_pick_tree_depth(
        self, parsed_instances: list[dict[str, Any]], object_roots: list[int]
    ) -> int:
        """根据内容复杂度自动选择紧凑树展开深度。

        参数：
            parsed_instances (list[dict[str, Any]]): 已解析实例列表。
            object_roots (list[int]): 根实例编号列表。

        返回：
            int: 自动选择的展开深度（1~4，复杂度越高深度越小）。
        """
        ref_links = 0
        for inst in parsed_instances:
            fields = inst.get("data", {}).get("fields")
            if isinstance(fields, dict):
                ref_links += self._count_reference_links(fields)

        # 实例越多、引用越密集，就越应该降低展开深度，避免 JSON 爆炸。
        complexity = max(len(parsed_instances), ref_links, len(object_roots) * 10)
        if complexity <= 1500:
            return 4
        if complexity <= 8000:
            return 3
        if complexity <= 30000:
            return 2
        return 1

    def _simplify_value_object(self, value: Any) -> Any:
        """简化只包含 `_Value` 的包装对象。

        参数：
            value (Any): 输入值。

        返回：
            Any: 形状为 ``{"_Value": x}`` 时返回 ``x``，否则原样返回输入。
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
        """按剩余深度展开紧凑值中的对象引用。

        参数：
            value (Any): 输入值（dict / list / 标量）。
            idx_map (dict[int, dict[str, Any]]): 实例编号到已解析实例的映射。
            depth (int): 剩余展开深度。
            visited (set[int]): 当前递归路径已访问实例集合，用于循环检测。

        返回：
            Any: 展开后的紧凑值；深度耗尽时保留 ``ref_instance_id`` 引用。
        """
        if isinstance(value, dict):
            if "ref_instance_id" in value and isinstance(value["ref_instance_id"], int):
                target_idx = value["ref_instance_id"]
                if depth <= 0:
                    return {"ref_instance_id": target_idx}
                # 每个递归分支都复制已访问集合，避免兄弟分支互相污染循环检测。
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
        """为一个根实例构造紧凑 JSON 树节点。

        参数：
            idx (int): 根实例编号。
            idx_map (dict[int, dict[str, Any]]): 已解析实例映射。
            depth (int): 剩余展开深度。
            instance_info_map (dict[int, dict[str, Any]] | None): 可选实例元数据映射，
                用于为未解析实例补充类名信息。
            visited (set[int] | None): 当前递归路径已访问实例集合，用于循环检测。

        返回：
            dict[str, Any]: 以类名为键包裹的紧凑 JSON 节点；遇到循环或缺失实例时
            返回带 ``cycle`` / ``missing`` / ``unparsed`` 标记的引用节点。
        """
        if visited is None:
            visited = set()
        if idx in visited:
            # 保留引用而不是继续展开，避免循环引用导致无限递归。
            return {"Ref": {"ref_instance_id": idx, "cycle": True}}
        visited.add(idx)

        inst = idx_map.get(idx)
        if inst is None:
            # 对未解析实例尽量保留类名和引用编号，方便用户定位。
            if instance_info_map is not None and idx in instance_info_map:
                class_name = instance_info_map[idx].get("class_name", "Unknown Class")
                class_name = self._normalize_to_fixed_enum_type(class_name)
                return {class_name: {"ref_instance_id": idx, "unparsed": True}}
            return {"Ref": {"ref_instance_id": idx, "missing": True}}

        if inst.get("is_userdata_reference"):
            # RSZ 用户数据表中的外部用户数据引用没有内联字段，
            # 导出为路径和引用编号形式。
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
            # 非字典结果统一包一层 value 键，保持节点结构一致。
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
        """使用实例元数据展开紧凑值。

        与 :meth:`_resolve_compact_value` 类似，但在展开引用时把
        ``instance_info_map`` 一并透传，便于为未解析实例补充类名。

        参数：
            value (Any): 输入值（dict / list / 标量）。
            idx_map (dict[int, dict[str, Any]]): 已解析实例映射。
            depth (int): 剩余展开深度。
            instance_info_map (dict[int, dict[str, Any]] | None): 实例元数据映射。
            visited (set[int]): 当前路径已访问实例集合，用于循环检测。

        返回：
            Any: 展开后的紧凑值；深度耗尽时保留 ``ref_instance_id`` 引用。
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
