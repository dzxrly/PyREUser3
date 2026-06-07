"""`.user.3` 字段级二进制读取逻辑。

本模块提供按 RE_RSZ 字段类型从二进制流中读取标量、数组和嵌套结构体的能力，
并在模板缺失或递归过深时保留原始字节，保证导出信息可逆、不丢失。
"""

from __future__ import annotations

from typing import Any

from ..core import (
    BinaryReader,
    ParseError,
    align,
    read_guid_like,
    read_len_c8,
    read_len_utf16,
)
from ..schema import ClassDef, FieldDef


class ExporterFieldParserMixin:
    """负责按 RE_RSZ 字段类型读取标量、数组和结构体。"""

    def _parse_scalar(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """按字段类型从二进制流中读取一个标量值。

        参数：
            reader (BinaryReader): 二进制读取器，会从其当前游标处读取。
            field (FieldDef): RE_RSZ 字段定义，决定读取方式与尺寸。
            depth (int): 当前结构体递归深度，用于限制嵌套结构体的展开层数。

        返回：
            Any: 解析出的 Python 值；标量为基础类型，对象/资源/结构体为 dict，
            未知类型则返回保留原始字节的 dict。
        """
        t = field.field_type
        # 基础数值类型直接按小端格式读取。
        if t == "Bool":
            return bool(reader.read_u8())
        if t == "S8":
            return reader.read_s8()
        if t == "U8":
            return reader.read_u8()
        if t == "S16":
            return reader.read_s16()
        if t == "U16":
            return reader.read_u16()
        if t in ("S32", "Sfix"):
            return reader.read_s32()
        if t == "Enum":
            return reader.read_s32()
        if t == "U32":
            return reader.read_u32()
        if t == "S64":
            return reader.read_s64()
        if t == "U64":
            return reader.read_u64()
        if t == "F32":
            return reader.read_f32()
        if t == "F64":
            return reader.read_f64()
        if t in ("Object", "UserData"):
            # 对象和用户数据字段在数据段中保存的是实例编号引用。
            return {"ref_instance_id": reader.read_s32()}
        if t in ("String", "Resource"):
            return read_len_utf16(reader)
        if t == "C8":
            return read_len_c8(reader)
        if t in ("Guid", "GameObjectRef", "Uri"):
            return read_guid_like(reader)
        if t == "Struct":
            if depth >= 4:
                # 结构体递归过深时保留原始字节，避免错误模板造成无限嵌套。
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {"raw": reader.read(to_read).hex(), "truncated": True}
            struct_hash = self.typedb.resolve_struct_hash(field.original_type)
            if struct_hash is None:
                # 模板中找不到结构体定义时也不丢数据，保留原始字节便于人工排查。
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {
                    "raw": reader.read(to_read).hex(),
                    "unknown_struct": field.original_type,
                }
            struct_cls = self.typedb.get_class(struct_hash)
            if struct_cls is None:
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {
                    "raw": reader.read(to_read).hex(),
                    "unknown_struct": field.original_type,
                }
            start = reader.tell()
            out: dict[str, Any] = {}
            for sf in struct_cls.fields:
                # 结构体内部字段仍然遵守各自的对齐规则。
                reader.seek(
                    align(reader.tell(), 4 if sf.is_array else max(sf.align, 1))
                )
                out[sf.name or "unnamed"] = self._parse_field_value(
                    reader, sf, depth=depth + 1
                )
            consumed = reader.tell() - start
            if field.size > consumed:
                # 结构体声明尺寸可能大于字段实际消费，跳过尾部填充。
                reader.seek(reader.tell() + (field.size - consumed))
            return out
        if t in {
            "Float2",
            "Float3",
            "Float4",
            "Vec2",
            "Vec3",
            "Vec4",
            "Quaternion",
            "Color",
            "AABB",
            "Capsule",
            "OBB",
            "Mat3",
            "Mat4",
            "Position",
        }:
            # 这些向量/矩阵类型按 4 字节浮点元素连续读取，数量由声明尺寸推断。
            count = max(field.size // 4, 1)
            return [reader.read_f32() for _ in range(count)]

        if field.size <= 0:
            return None
        to_read = max(0, min(field.size, reader.size - reader.tell()))
        # 未识别类型保留原始十六进制内容，避免封包信息不可逆丢失。
        return {"raw": reader.read(to_read).hex(), "type": t}

    def _parse_field_value(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """读取字段值，自动处理数组与标量分支。

        参数：
            reader (BinaryReader): 二进制读取器。
            field (FieldDef): 字段定义。
            depth (int): 当前结构体递归深度。

        返回：
            Any: 数组字段返回元素列表，非数组字段返回单个标量值。
        """
        if field.is_array:
            count = reader.read_u32()
            if count > 1_000_000:
                # 明显异常的数组长度通常意味着模板或游标已错位，直接返回空数组。
                return []
            items = []
            for _ in range(count):
                if reader.tell() >= reader.size:
                    break
                reader.seek(align(reader.tell(), max(field.align, 1)))
                # 数组头保存元素数量，元素本身按非数组字段解析。
                non_array = FieldDef(
                    name=field.name,
                    field_type=field.field_type,
                    original_type=field.original_type,
                    size=field.size,
                    align=field.align,
                    is_array=False,
                )
                items.append(self._parse_scalar(reader, non_array, depth=depth))
            return items
        return self._parse_scalar(reader, field, depth=depth)

    def _estimate_min_instance_size(self, cls: ClassDef) -> int:
        """估算一个实例至少会占用多少字节。

        参数：
            cls (ClassDef): 类型定义。

        返回：
            int: 估算的最小实例字节数（至少为 1）。
        """
        pos = 0
        for field in cls.fields:
            # 估算只用于解析失败后的游标跳过，因此宁可保守也不做复杂展开。
            align_to = 4 if field.is_array else max(field.align, 1)
            pos = align(pos, align_to)
            t = field.field_type
            if field.is_array:
                pos += 4
            elif t in ("String", "Resource", "C8"):
                pos += 4
            elif t in ("Object", "UserData"):
                pos += 4
            elif t in ("Guid", "GameObjectRef", "Uri"):
                pos += 16
            elif t in ("S8", "U8", "Bool"):
                pos += 1
            elif t in ("S16", "U16"):
                pos += 2
            elif t in ("S32", "U32", "Enum", "Sfix", "F32"):
                pos += 4
            elif t in ("S64", "U64", "F64"):
                pos += 8
            else:
                pos += max(field.size, 0)
        return max(pos, 1)

    def _parse_instance(self, reader: BinaryReader, class_hash: int) -> dict[str, Any]:
        """解析一个类型实例的数据段。

        参数：
            reader (BinaryReader): 二进制读取器。
            class_hash (int): 实例表中的类型哈希。

        返回：
            dict[str, Any]: 含 ``_class``（类名）和 ``fields``（字段名 -> 值）的实例字典。

        异常：
            ParseError: 当类型哈希在模板中找不到时抛出。
        """
        cls = self.typedb.get_class(class_hash)
        if cls is None:
            raise ParseError(f"class hash 0x{class_hash:08x} not found in schema")
        out: dict[str, Any] = {"_class": cls.name, "fields": {}}
        for field in cls.fields:
            # 每个字段读取前都按模板声明的对齐要求推进游标。
            reader.seek(
                align(reader.tell(), 4 if field.is_array else max(field.align, 1))
            )
            out["fields"][field.name or "unnamed"] = self._parse_field_value(
                reader, field, depth=0
            )
        return out
