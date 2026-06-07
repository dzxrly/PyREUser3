"""封包阶段共享的数据结构与二进制写入器。

这里定义规划（plan）阶段产出、写入（writer）阶段消费的中间数据结构：
实例引用、结构体值、实例规格，以及一个支持对齐填充的小端二进制写入器。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from ..core import PACK_JSON_FORMAT, ParseError, align
from ..schema import ClassDef


class PackError(ParseError):
    """JSON 数据无法编码为 `.user.3` 时抛出的异常。

    继承自 :class:`ParseError`，用于把封包阶段可预期的输入错误（缺类、悬空
    引用、不支持的数据段等）与程序内部错误区分开。
    """


@dataclass(frozen=True)
class InstanceRef:
    """RSZ 实例表中的对象引用。

    属性：
        index (int): 被引用实例在实例表中的编号；0 表示空引用。
    """

    index: int


@dataclass
class StructValue:
    """待写入的结构体值和声明尺寸。

    属性：
        class_def (ClassDef): 结构体对应的类型定义。
        fields (dict[str, Any]): 结构体内部字段名到字段值的映射。
        declared_size (int): 模板声明的结构体字节尺寸，用于尾部补齐。
    """

    class_def: ClassDef
    fields: dict[str, Any]
    declared_size: int


@dataclass
class InstanceSpec:
    """封包前规划出的一个 RSZ 实例。

    属性：
        class_hash (int): 实例类型哈希。
        class_def (ClassDef): 实例对应的类型定义。
        fields (dict[str, Any]): 准备好的字段名到字段值映射，默认空字典。
    """

    class_hash: int
    class_def: ClassDef
    fields: dict[str, Any] = field(default_factory=dict)


class BinaryWriter:
    """带对齐辅助的小端二进制写入器。

    内部维护一个可增长的字节缓冲区，提供原始写入、按 ``struct`` 格式写入，
    以及对齐/填充到指定偏移的能力。
    """

    def __init__(self) -> None:
        """初始化空的字节缓冲区。

        返回：
            None: 构造函数，仅初始化内部缓冲区。
        """
        self.data = bytearray()

    def tell(self) -> int:
        """返回当前写入偏移。

        返回：
            int: 已写入的字节数（即下一个写入位置）。
        """
        return len(self.data)

    def write(self, raw: bytes) -> None:
        """追加原始字节。

        参数：
            raw (bytes): 要追加到缓冲区末尾的字节。

        返回：
            None: 原地修改内部缓冲区。
        """
        self.data.extend(raw)

    def write_struct(self, fmt: str, *values: Any) -> None:
        """按 `struct` 格式打包并写入数值。

        参数：
            fmt (str): :func:`struct.pack` 使用的格式字符串。
            *values (Any): 与 ``fmt`` 对应的待打包数值。

        返回：
            None: 把打包后的字节追加到缓冲区。
        """
        self.write(struct.pack(fmt, *values))

    def align(self, alignment: int) -> None:
        """用零字节填充到指定对齐边界。

        参数：
            alignment (int): 对齐粒度（字节）。

        返回：
            None: 必要时向缓冲区追加零字节。
        """
        target = align(self.tell(), alignment)
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))

    def pad_to(self, target: int) -> None:
        """填充到绝对偏移，禁止回退写入。

        参数：
            target (int): 目标绝对偏移，必须大于等于当前偏移。

        返回：
            None: 必要时向缓冲区追加零字节。

        异常：
            PackError: 当目标偏移小于当前偏移（需要回退）时抛出。
        """
        if target < self.tell():
            raise PackError(f"cannot pad backwards: {self.tell()} -> {target}")
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))
