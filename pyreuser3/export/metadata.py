"""导出阶段的枚举元数据处理逻辑。

本模块在导出器内部维护多个运行期索引：固定枚举的“值 -> 名称”查找表、
“成员名 -> 可能所属枚举类型”的反向索引，以及字段/可序列化类型/泛型容器的
枚举上下文。这些索引来源于显式传入的 ``il2cpp_dump.json``，用于把数值枚举
转换成可读标签。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core import ParseError
from ..rich_ui import get_console


class ExporterMetadataMixin:
    """负责从 il2cpp dump 中提取和应用枚举上下文。"""

    @staticmethod
    def _id_formatter(key: str, value: int) -> str:
        """把枚举值格式化为导出 JSON 中的可读标签。

        参数：
            key (str): 枚举成员名。
            value (int): 固定枚举数值。

        返回：
            str: 形如 ``[123] MemberName`` 的可读标签。
        """
        return f"[{value}] {key}"

    @staticmethod
    def _to_u32(value: int) -> int:
        """把整数转换到无符号 32 位范围。

        参数：
            value (int): 输入整数。

        返回：
            int: 无符号 32 位值（0 ~ 0xFFFFFFFF）。
        """
        return value & 0xFFFFFFFF

    @staticmethod
    def _to_s32(value: int) -> int:
        """把整数转换为有符号 32 位表示。

        参数：
            value (int): 输入整数。

        返回：
            int: 有符号 32 位值（-0x80000000 ~ 0x7FFFFFFF）。
        """
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000

    def _build_enum_lookup_from_enums_internal(
        self, raw: Any
    ) -> dict[str, dict[int, tuple[str, int]]]:
        """根据 `Enums_Internal` 形状的数据建立固定枚举查找表。

        参数：
            raw (Any): ``export_enums_internal`` 产出的 ``枚举类型 -> {成员名 -> 值}`` 映射。

        返回：
            dict[str, dict[int, tuple[str, int]]]: ``固定枚举类型 -> {数值 -> (成员名, 原始值)}``
            的查找表，仅包含以 ``_Fixed`` 结尾的枚举类型。
        """
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
                # 同一个底层 32 位值在 JSON 中可能以有符号或无符号形式出现，
                # 两种写法都映射回同一个枚举成员，减少后处理分支。
                value_map[self._to_s32(raw_value)] = entry
                value_map[self._to_u32(raw_value)] = entry
            if value_map:
                lookup[enum_type] = value_map
        return lookup

    def _load_enum_lookup(self) -> dict[str, dict[int, tuple[str, int]]]:
        """兼容钩子：当前版本只从显式 il2cpp 输入构建枚举表。

        返回：
            dict[str, dict[int, tuple[str, int]]]: 始终为空映射；真实枚举表由
            :meth:`_ensure_internal_metadata_files` 生成。
        """
        return {}

    def _resolve_il2cpp_dump_path(self) -> Path | None:
        """返回显式传入且存在的 `il2cpp_dump.json` 路径。

        返回：
            Path | None: 文件存在时返回其路径，否则返回 ``None``。
        """
        return self.il2cpp_dump_path if self.il2cpp_dump_path.is_file() else None

    def _ensure_internal_metadata_files(self) -> dict:
        """根据必填 il2cpp dump 在输出目录生成 `Enums_Internal.json`。

        返回：
            dict: 从 dump 中提取的内部枚举映射（``枚举类型 -> {成员名 -> 值}``）。

        异常：
            FileNotFoundError: 当 ``il2cpp_dump.json`` 不存在时抛出。
            ParseError: 当读取或解析 dump 失败时抛出。
        """
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
        # 这个文件是导出结果的一部分，方便用户排查枚举数值来源。
        with enums_out.open("w", encoding="utf-8") as f:
            json.dump(enums_internal, f, ensure_ascii=False, indent=2)
        return enums_internal

    def _rebuild_enum_member_index(self) -> None:
        """建立反向索引：枚举成员名 -> 可能所属的固定枚举类型。

        遍历当前 ``enum_lookup``，把每个成员名映射到所有可能包含它的枚举类型，
        供后续根据“成员名 + 数值”反推唯一枚举类型。

        返回：
            None: 直接重建 ``self.enum_member_to_types``。
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
        """根据成员名和具体数值反推出唯一的枚举类型。

        参数：
            member_name (str): 枚举成员名。
            value (int): 该成员对应的数值。

        返回：
            str | None: 唯一匹配时返回固定枚举类型名；无候选或多重匹配时返回 ``None``。
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
        # 多个类型同时匹配时不猜测，避免把字段错误标成另一个枚举。
        return None

    def _apply_enum_context(self, raw: dict) -> None:
        """把枚举上下文应用到导出器的运行时索引。

        参数：
            raw (dict): 从 il2cpp dump 提取出的枚举上下文对象，含
                ``class_field_fixed_types``、``serializable_to_fixed``、
                ``generic_container_rules`` 等键。

        返回：
            None: 重建 ``class_field_fixed_types`` / ``serializable_to_fixed`` /
            ``generic_container_rules`` / ``param_type_default_enum`` 四个索引。
        """
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
                    # 只接受 `*_Fixed`，避免普通类型名误入枚举转换流程。
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
        # 临时收集“参数类型 -> 枚举类型集合”，用于推断每个参数类型的默认枚举。
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
                # 同一参数类型只被一个枚举容器使用时，可作为默认枚举类型。
                self.param_type_default_enum[param_type] = next(iter(enum_types))

    def _load_enum_context_from_il2cpp_dump(self) -> bool:
        """直接从 il2cpp dump 加载枚举上下文。

        返回：
            bool: 成功读取并应用上下文返回 ``True``；dump 缺失或读取失败返回 ``False``。
        """
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
        """检查枚举表和上下文是否可用，并在缺失时输出警告。

        枚举表缺失不会阻止导出，只会让数值保持原始整数形式。

        返回：
            None: 重建成员索引；必要时通过 Rich 控制台打印告警。
        """
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
