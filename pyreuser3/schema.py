"""RE_RSZ 模板类型数据库。

本模块负责把外部的 RE_RSZ 模板 JSON 加载成内存中的类型索引，供导出器和
封包器按类型哈希查找字段布局，并提供 RE_RSZ 类型名常用的 MurmurHash3 计算。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """计算 RE_RSZ 类型名常用的 MurmurHash3 32 位哈希。

    参数：
        data (bytes): 输入字节，通常是 UTF-8 编码的类型名。
        seed (int): 哈希种子，RE_RSZ 模板通常使用 ``0xFFFFFFFF``。

    返回：
        int: 32 位无符号哈希值（0 ~ 0xFFFFFFFF）。
    """
    c1 = 0xCC9E2D51
    c2 = 0x1B873593
    h1 = seed & 0xFFFFFFFF
    length = len(data)
    # 主体按 4 字节块处理，rounded_end 是最后一个完整块的结束位置。
    rounded_end = length & ~0x3

    # MurmurHash3 以 4 字节块为主体处理，尾部不足 4 字节再单独混合。
    for i in range(0, rounded_end, 4):
        k1 = int.from_bytes(data[i : i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    # 处理尾部 1-3 字节。这里严格保持小端序位移顺序。
    k1 = 0
    tail = data[rounded_end:]
    if len(tail) == 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    # 最终混合阶段把长度和高低位充分混合，得到最终 32 位结果。
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


@dataclass
class FieldDef:
    """RE_RSZ 模板中的字段定义。

    描述一个类型内单个字段的二进制布局信息，是解析和封包时按类型读写
    数据段的依据。

    属性：
        name (str): 字段名；模板中可能为空字符串。
        field_type (str): 字段的逻辑类型（如 ``S32``、``String``、``Struct`` 等）。
        original_type (str): 字段在游戏中的原始类型名，用于结构体/枚举推断。
        size (int): 字段声明的字节尺寸。
        align (int): 字段要求的对齐字节数。
        is_array (bool): 是否为数组字段（数组带 4 字节长度前缀）。
    """

    name: str
    field_type: str
    original_type: str
    size: int
    align: int
    is_array: bool


@dataclass
class ClassDef:
    """RE_RSZ 模板中的类型定义。

    属性：
        name (str): 类型完整名称（通常含命名空间）。
        crc (int): 类型的 CRC 校验值，写回 RSZ 实例表时需要。
        fields (list[FieldDef]): 按声明顺序排列的字段列表。
    """

    name: str
    crc: int
    fields: list[FieldDef]


class TypeDB:
    """封装 RE_RSZ 模板中的类型索引。

    内部以“类型哈希 -> 类型定义”为主索引，并额外维护“类型名 -> 哈希”的
    反查表，供封包阶段从 JSON 中的类名还原出类型哈希。
    """

    def __init__(self, classes: dict[int, ClassDef]):
        """初始化类型数据库。

        参数：
            classes (dict[int, ClassDef]): 以类型哈希为键、类型定义为值的映射。
        """
        self.classes = classes
        # name_to_hash 用于封包时从 JSON 类名反查类型哈希。
        self.name_to_hash = {c.name: h for h, c in classes.items()}

    @classmethod
    def load(cls, json_path: Path) -> "TypeDB":
        """从 RE_RSZ 模板 JSON 读取并构建类型数据库。

        参数：
            json_path (Path): 模板 JSON 文件路径。

        返回：
            TypeDB: 已加载完毕、可供查询的类型数据库实例。
        """
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        classes: dict[int, ClassDef] = {}
        for key, value in raw.items():
            try:
                # RE_RSZ 模板通常以十六进制字符串保存类型哈希。
                class_hash = int(key, 16)
            except ValueError:
                # 非十六进制键（如说明性字段）直接跳过，不影响类型加载。
                continue
            fields: list[FieldDef] = []
            for field in value.get("fields", []):
                # 字段缺省值尽量保守，保证模板中少数字段缺属性时仍能加载。
                fields.append(
                    FieldDef(
                        name=field.get("name", ""),
                        field_type=field.get("type", "Data"),
                        original_type=field.get("original_type", ""),
                        size=int(field.get("size", 0)),
                        align=int(field.get("align", 1)),
                        is_array=bool(field.get("array", False)),
                    )
                )
            crc_raw = value.get("crc", "0")
            # CRC 可能是十六进制字符串，也可能已经是整数，两种都兼容。
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""), crc=crc, fields=fields
            )
        return cls(classes)

    def get_class(self, class_hash: int) -> ClassDef | None:
        """按类型哈希查询类型定义。

        参数：
            class_hash (int): RE_RSZ 类型哈希。

        返回：
            ClassDef | None: 对应的类型定义；不存在时返回 ``None``。
        """
        return self.classes.get(class_hash)

    def resolve_struct_hash(self, original_type: str) -> int | None:
        """把结构体类型名解析为类型哈希。

        参数：
            original_type (str): 模板字段中记录的原始结构体类型名。

        返回：
            int | None: 找到的类型哈希；无法解析时返回 ``None``。
        """
        if not original_type:
            return None
        known = self.name_to_hash.get(original_type)
        if known is not None:
            return known
        # 有些结构体不会直接出现在 name_to_hash 中，需要按 RE_RSZ 规则
        # 对类型名做 MurmurHash3 后再查模板。
        maybe = murmur3_32(original_type.encode("utf-8"), seed=0xFFFFFFFF)
        if maybe in self.classes:
            return maybe
        return None
