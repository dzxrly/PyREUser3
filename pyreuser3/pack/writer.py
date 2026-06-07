"""RSZ/USR 二进制写回逻辑。

写入阶段消费规划阶段产出的实例列表，按 RE Engine 物理布局拼出字节：先连续
写入各实例数据段，再写 RSZ 头、对象表、实例表，最后包上最小 USR 头。字段值
按类型写入，并兼容枚举标签/成员名、原始字节回写等多种来源。
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .models import BinaryWriter, InstanceRef, PackError, StructValue
from ..core import align
from ..schema import FieldDef

# 匹配导出格式 `[123] MemberName`，用于从枚举标签中取出括号内数值。
ENUM_LABEL_RE = re.compile(r"^\[(-?\d+)\]\s*(.*)$")


class PackerWriterMixin:
    """负责把规划后的实例表编码成 `.user.3` 字节。"""

    def _build_binary(self, root_ids: list[int]) -> bytes:
        """构造完整 USR + RSZ 二进制内容。

        参数：
            root_ids (list[int]): 根实例编号列表，写入 RSZ 对象表。

        返回：
            bytes: 完整的 ``.user.3`` 二进制字节。
        """
        data_writer = BinaryWriter()
        for spec in self.instances[1:]:
            if spec is None:
                continue
            # 先连续写入所有实例的数据段，稍后再计算 RSZ 表偏移。
            self._write_instance(data_writer, spec)

        object_count = len(root_ids)
        instance_count = len(self.instances)
        # 对象表紧跟 48 字节 RSZ 头，实例表再随其后，数据段按 16 字节对齐。
        instance_offset = 48 + object_count * 4
        data_offset = align(instance_offset + instance_count * 8, 16)

        rsz_writer = BinaryWriter()
        # RSZ 头固定为 48 字节，偏移均相对 RSZ 块起点。
        rsz_writer.write_struct(
            "<IIiiiiqqq",
            self.rsz_magic,
            16,
            object_count,
            instance_count,
            0,
            0,
            instance_offset,
            data_offset,
            data_offset,
        )
        for root_id in root_ids:
            rsz_writer.write_struct("<i", root_id)
        rsz_writer.pad_to(instance_offset)
        # 实例 0 是空引用槽，对应哈希和 CRC 均为 0。
        rsz_writer.write_struct("<II", 0, 0)
        for spec in self.instances[1:]:
            if spec is None:
                continue
            rsz_writer.write_struct("<II", spec.class_hash, spec.class_def.crc)
        rsz_writer.pad_to(data_offset)
        rsz_writer.write(bytes(data_writer.data))

        usr_writer = BinaryWriter()
        # 当前封包器生成最小 USR 头：资源表和用户数据表为空，数据偏移指向 RSZ。
        usr_writer.write_struct("<IiiiQQQ", self.user_magic, 0, 0, 0, 0x30, 0x30, 0x30)
        usr_writer.write(b"\x00" * 8)
        usr_writer.write(bytes(rsz_writer.data))
        return bytes(usr_writer.data)

    def _write_instance(self, writer: BinaryWriter, spec: InstanceSpec) -> None:
        """按模板字段顺序写入一个实例。

        参数：
            writer (BinaryWriter): 目标二进制写入器（数据段）。
            spec (InstanceSpec): 规划好的实例规格。

        返回：
            None: 把实例数据写入 ``writer``。
        """
        for field_def in spec.class_def.fields:
            # 数组字段按 4 字节对齐，普通字段按模板声明的对齐值对齐。
            writer.align(4 if field_def.is_array else max(field_def.align, 1))
            key = field_def.name or "unnamed"
            self._write_field(writer, field_def, spec.fields.get(key))

    def _write_field(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """写入一个字段，自动处理数组和标量。

        参数：
            writer (BinaryWriter): 目标二进制写入器。
            field_def (FieldDef): 字段定义。
            value (Any): 字段的中间表示值。

        返回：
            None: 把字段数据写入 ``writer``。
        """
        if field_def.is_array:
            items = value if isinstance(value, list) else []
            writer.write_struct("<I", len(items))
            non_array = FieldDef(
                name=field_def.name,
                field_type=field_def.field_type,
                original_type=field_def.original_type,
                size=field_def.size,
                align=field_def.align,
                is_array=False,
            )
            for item in items:
                writer.align(max(field_def.align, 1))
                # 数组元素不再写数组头，按非数组字段写入。
                self._write_scalar(writer, non_array, item)
            return
        self._write_scalar(writer, field_def, value)

    def _write_scalar(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """按字段类型写入标量值。

        参数：
            writer (BinaryWriter): 目标二进制写入器。
            field_def (FieldDef): 字段定义，决定写入格式与尺寸。
            value (Any): 待写入的标量值（可能是数字、字符串、引用或保留原始字节的 dict）。

        返回：
            None: 把标量数据写入 ``writer``；无法识别的类型按声明尺寸补零。
        """
        t = field_def.field_type
        if t == "Bool":
            writer.write_struct("<B", 1 if bool(value) else 0)
            return
        if t == "S8":
            writer.write_struct("<b", self._coerce_int(value, field_def))
            return
        if t == "U8":
            writer.write_struct("<B", self._coerce_int(value, field_def) & 0xFF)
            return
        if t == "S16":
            writer.write_struct("<h", self._coerce_int(value, field_def))
            return
        if t == "U16":
            writer.write_struct("<H", self._coerce_int(value, field_def) & 0xFFFF)
            return
        if t in {"S32", "Enum", "Sfix"}:
            writer.write_struct("<i", self._to_s32(self._coerce_int(value, field_def)))
            return
        if t == "U32":
            writer.write_struct("<I", self._coerce_int(value, field_def) & 0xFFFFFFFF)
            return
        if t == "S64":
            writer.write_struct("<q", self._coerce_int(value, field_def))
            return
        if t == "U64":
            writer.write_struct(
                "<Q", self._coerce_int(value, field_def) & 0xFFFFFFFFFFFFFFFF
            )
            return
        if t == "F32":
            writer.write_struct("<f", float(value or 0.0))
            return
        if t == "F64":
            writer.write_struct("<d", float(value or 0.0))
            return
        if t in {"Object", "UserData"}:
            # 对象字段最终只写入目标实例编号。
            ref_id = (
                value.index
                if isinstance(value, InstanceRef)
                else self._coerce_int(value, field_def)
            )
            writer.write_struct("<i", ref_id)
            return
        if t in {"String", "Resource"}:
            # RE Engine 字符串保存长度前缀，并以 UTF-16LE 空字符结尾。
            writer.align(4)
            raw = f"{value or ''}\x00".encode("utf-16-le")
            writer.write_struct("<I", len(raw) // 2)
            writer.write(raw)
            return
        if t == "C8":
            # C8 使用 UTF-8 字节长度，同样保留结尾空字符。
            writer.align(4)
            raw = f"{value or ''}\x00".encode("utf-8")
            writer.write_struct("<I", len(raw))
            writer.write(raw)
            return
        if t in {"Guid", "GameObjectRef", "Uri"}:
            writer.write(uuid.UUID(str(value)).bytes_le)
            return
        if t == "Struct":
            self._write_struct(writer, value)
            return
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
            # 向量/矩阵类型按 4 字节浮点元素写入，不足部分补 0。
            values = value if isinstance(value, list) else []
            count = max(field_def.size // 4, 1)
            for i in range(count):
                writer.write_struct("<f", float(values[i]) if i < len(values) else 0.0)
            return
        if isinstance(value, dict) and isinstance(value.get("raw"), str):
            # 未知字段或未知结构体保留原始十六进制时，尽量原样写回。
            writer.write(bytes.fromhex(value["raw"]))
            return
        # 仍无法识别时按声明尺寸补零，保证后续字段偏移不被破坏。
        writer.write(b"\x00" * max(field_def.size, 0))

    def _write_struct(self, writer: BinaryWriter, value: Any) -> None:
        """写入结构体字段。

        参数：
            writer (BinaryWriter): 目标二进制写入器。
            value (Any): 结构体值，应为 :class:`StructValue`；保留原始字节的 dict 也可。

        返回：
            None: 把结构体数据写入 ``writer``，并按声明尺寸补齐尾部填充。
        """
        if not isinstance(value, StructValue):
            raw = value.get("raw") if isinstance(value, dict) else None
            if isinstance(raw, str):
                writer.write(bytes.fromhex(raw))
            return
        start = writer.tell()
        for field_def in value.class_def.fields:
            writer.align(4 if field_def.is_array else max(field_def.align, 1))
            key = field_def.name or "unnamed"
            self._write_field(writer, field_def, value.fields.get(key))
        consumed = writer.tell() - start
        if value.declared_size > consumed:
            # 结构体实际字段小于声明尺寸时，需要补齐尾部填充。
            writer.write(b"\x00" * (value.declared_size - consumed))

    def _coerce_int(self, value: Any, field_def: FieldDef) -> int:
        """把 JSON 值转换为整数，兼容枚举标签和成员名。

        参数：
            value (Any): JSON 值：布尔、整数、浮点或字符串（数字 / ``[值] 名称`` / 成员名）。
            field_def (FieldDef): 字段定义，提供枚举成员反查所需的类型上下文。

        返回：
            int: 转换后的整数值。

        异常：
            PackError: 当值无法解析为整数且不是已知枚举成员名时抛出。
        """
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            match = ENUM_LABEL_RE.match(text)
            if match:
                # 导出格式 `[123] MemberName` 优先使用括号内数值。
                return int(match.group(1))
            try:
                return int(text, 0)
            except ValueError:
                # 如果不是数字字符串，再尝试按枚举成员名反查。
                enum_value = self._resolve_enum_member(text, field_def)
                if enum_value is not None:
                    return enum_value
        raise PackError(f"cannot convert {value!r} to int for field {field_def.name}")

    def _resolve_enum_member(self, text: str, field_def: FieldDef) -> int | None:
        """按字段类型上下文把枚举成员名解析成数值。

        参数：
            text (str): 枚举成员名。
            field_def (FieldDef): 字段定义，其原始类型用于推断对应的固定枚举类型。

        返回：
            int | None: 命中时返回成员数值；无法解析时返回 ``None``。
        """
        candidates = []
        original = field_def.original_type
        if original.endswith("_Serializable"):
            candidates.append(f"{original[:-13]}_Fixed")
        if original.endswith("_Fixed"):
            candidates.append(original)
        for enum_type in candidates:
            member_map = self.member_lookup.get(enum_type)
            if member_map and text in member_map:
                return member_map[text]
        return None
