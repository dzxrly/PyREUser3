"""Binary writer helpers for .user.3 packing."""

from __future__ import annotations

import re
import uuid
from typing import Any

from .models import BinaryWriter, InstanceRef, PackError, StructValue
from ..core import align
from ..schema import FieldDef

# Keep enum metadata consistent while converting values.
ENUM_LABEL_RE = re.compile(r"^\[(-?\d+)\]\s*(.*)$")


class PackerWriterMixin:
    """Mixin that writes planned instances back to binary .user.3 data."""

    def _build_binary(self, root_ids: list[int]) -> bytes:
        """Internal helper for build binary."""
        data_writer = BinaryWriter()
        for spec in self.instances[1:]:
            if spec is None:
                continue
            # Keep instance references stable while parsing or packing data.
            self._write_instance(data_writer, spec)

        object_count = len(root_ids)
        instance_count = len(self.instances)
        # Keep instance references stable while parsing or packing data.
        instance_offset = 48 + object_count * 4
        data_offset = align(instance_offset + instance_count * 8, 16)

        rsz_writer = BinaryWriter()
        # Honor binary alignment and offset rules.
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
        # Keep instance references stable while parsing or packing data.
        rsz_writer.write_struct("<II", 0, 0)
        for spec in self.instances[1:]:
            if spec is None:
                continue
            rsz_writer.write_struct("<II", spec.class_hash, spec.class_def.crc)
        rsz_writer.pad_to(data_offset)
        rsz_writer.write(bytes(data_writer.data))

        usr_writer = BinaryWriter()
        # Honor binary alignment and offset rules.
        usr_writer.write_struct("<IiiiQQQ", self.user_magic, 0, 0, 0, 0x30, 0x30, 0x30)
        usr_writer.write(b"\x00" * 8)
        usr_writer.write(bytes(rsz_writer.data))
        return bytes(usr_writer.data)

    def _write_instance(self, writer: BinaryWriter, spec: InstanceSpec) -> None:
        """Internal helper for write instance."""
        for field_def in spec.class_def.fields:
            # Preserve field layout details for binary compatibility.
            writer.align(4 if field_def.is_array else max(field_def.align, 1))
            key = field_def.name or "unnamed"
            self._write_field(writer, field_def, spec.fields.get(key))

    def _write_field(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Internal helper for write field."""
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
                # Preserve field layout details for binary compatibility.
                self._write_scalar(writer, non_array, item)
            return
        self._write_scalar(writer, field_def, value)

    def _write_scalar(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Internal helper for write scalar."""
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
            # Keep instance references stable while parsing or packing data.
            ref_id = (
                value.index
                if isinstance(value, InstanceRef)
                else self._coerce_int(value, field_def)
            )
            writer.write_struct("<i", ref_id)
            return
        if t in {"String", "Resource"}:
            # Preserve string and GUID decoding behavior.
            writer.align(4)
            raw = f"{value or ''}\x00".encode("utf-16-le")
            writer.write_struct("<I", len(raw) // 2)
            writer.write(raw)
            return
        if t == "C8":
            # Keep this implementation detail explicit.
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
            # Keep this implementation detail explicit.
            values = value if isinstance(value, list) else []
            count = max(field_def.size // 4, 1)
            for i in range(count):
                writer.write_struct("<f", float(values[i]) if i < len(values) else 0.0)
            return
        if isinstance(value, dict) and isinstance(value.get("raw"), str):
            # Preserve field layout details for binary compatibility.
            writer.write(bytes.fromhex(value["raw"]))
            return
        # Preserve field layout details for binary compatibility.
        writer.write(b"\x00" * max(field_def.size, 0))

    def _write_struct(self, writer: BinaryWriter, value: Any) -> None:
        """Internal helper for write struct."""
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
            # Preserve field layout details for binary compatibility.
            writer.write(b"\x00" * (value.declared_size - consumed))

    def _coerce_int(self, value: Any, field_def: FieldDef) -> int:
        """Internal helper for coerce int."""
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
                # Keep this implementation detail explicit.
                return int(match.group(1))
            try:
                return int(text, 0)
            except ValueError:
                # Keep enum metadata consistent while converting values.
                enum_value = self._resolve_enum_member(text, field_def)
                if enum_value is not None:
                    return enum_value
        raise PackError(f"cannot convert {value!r} to int for field {field_def.name}")

    def _resolve_enum_member(self, text: str, field_def: FieldDef) -> int | None:
        """Internal helper for resolve enum member."""
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
