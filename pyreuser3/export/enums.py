"""从 il2cpp dump 提取枚举源数据的逻辑。

REFramework 导出的 ``il2cpp_dump.json`` 里包含大量类型/字段/方法信息。本模块
负责从中抽取两类资料：枚举成员表（值 -> 名称），以及把字段、可序列化包装
类型和泛型容器关联到“固定枚举”（``*_Fixed``）的上下文，供导出后处理使用。
"""

from __future__ import annotations

import re
from typing import Any

from ..core import ENUM_UNUSED_KEY


class ExporterEnumSourceMixin:
    """负责把 REFramework dump 转换成导出器可用的枚举原始资料。"""

    @staticmethod
    def export_enums_internal(dump_json: dict) -> dict:
        """从 `il2cpp_dump.json` 中提取枚举成员表。

        参数：
            dump_json (dict): 已解析的 il2cpp dump 对象。

        返回：
            dict: ``枚举类型 -> {成员名 -> 数值}`` 的映射。
        """
        enums_internal = {}
        for key, value in dump_json.items():
            if isinstance(value, dict):
                obj = dump_json[key]
                # REFramework dump 中枚举类型的 parent 通常为 System.Enum。
                if "parent" in obj and obj["parent"] == "System.Enum":
                    val = {}
                    for _k, _v in obj["fields"].items():
                        # 跳过枚举的占位字段（value__），只保留真实成员。
                        if _k != ENUM_UNUSED_KEY:
                            val[_k] = _v["default"]
                    enums_internal[key] = val
        return enums_internal

    @staticmethod
    def export_enum_context_internal(dump_json: dict) -> dict:
        """从 il2cpp dump 中提取枚举字段上下文。

        参数：
            dump_json (dict): 已解析的 il2cpp dump 对象。

        返回：
            dict: 含三个键的上下文字典：``class_field_fixed_types``（类 -> 字段 -> 枚举类型）、
            ``serializable_to_fixed``（可序列化包装类型 -> 固定枚举）、
            ``generic_container_rules``（泛型容器 -> {param_type, enum_type}）。
        """

        def extract_fixed_enum_type(type_name: Any) -> str | None:
            """从类型表达式中提取唯一的 `*_Fixed` 枚举类型。

            参数：
                type_name (Any): 字段、方法参数或返回值上的类型表达式（通常是 str）。

            返回：
                str | None: 找到且唯一时返回枚举类型名，否则返回 ``None``。
            """
            if not isinstance(type_name, str):
                return None
            matches = re.findall(r"[A-Za-z0-9_.]+_Fixed", type_name)
            if not matches:
                return None
            # 去重后若只剩一个候选，才能确定字段唯一对应的固定枚举类型。
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

            # RSZ 元数据也是字段名到枚举类型关系的权威来源。
            rsz_fields = obj.get("RSZ")
            if isinstance(rsz_fields, list):
                for rsz_field in rsz_fields:
                    if not isinstance(rsz_field, dict):
                        continue
                    potential_name = rsz_field.get("potential_name")
                    fixed_type = extract_fixed_enum_type(rsz_field.get("type"))
                    if isinstance(potential_name, str) and fixed_type is not None:
                        field_map.setdefault(potential_name, fixed_type)

            # 反射属性里可能带有数组元素类型信息，也可以补充字段上下文。
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
                # `xxx_Serializable` 往往是固定枚举的可序列化包装类型。
                # 如果方法签名里只出现一个 `*_Fixed`，即可建立一对一映射。
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
                # 泛型容器常见形态是 <枚举类型, 参数类型>，后处理时可用它
                # 推断参数对象内部 `_FixedID` 等字段对应哪个枚举。
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
