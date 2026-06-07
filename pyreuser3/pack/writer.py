"""Serialize planned RSZ instances into the binary .user.3 format.

The writer handles USR and RSZ headers, object and instance tables, field alignment,
strings, arrays, structs, enum values, and raw byte preservation.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .models import BinaryWriter, InstanceRef, PackError, StructValue
from ..core import align
from ..schema import FieldDef

# Register enum values through the shared lookup tables so readable labels and numeric
# packing stay reversible.
ENUM_LABEL_RE = re.compile(r"^\[(-?\d+)\]\s*(.*)$")


class PackerWriterMixin:
    """Serialize planned instances, tables, headers, and field values into the binary .user.3
    layout.
    """

    def _build_binary(self, root_ids: list[int]) -> bytes:
        """Build binary.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            root_ids (list[int]): Collection of identifiers used for validation.

        Returns:
            bytes: Encoded binary data ready to write to disk.
        """
        data_writer = BinaryWriter()
        for spec in self.instances[1:]:
            if spec is None:
                continue
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            self._write_instance(data_writer, spec)

        object_count = len(root_ids)
        instance_count = len(self.instances)
        # Preserve instance numbering and reference identity; RSZ object links depend on
        # these indexes remaining stable.
        instance_offset = 48 + object_count * 4
        data_offset = align(instance_offset + instance_count * 8, 16)

        rsz_writer = BinaryWriter()
        # Apply RE Engine alignment and offset rules before touching binary fields;
        # later table offsets assume this layout.
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
        # Preserve instance numbering and reference identity; RSZ object links depend on
        # these indexes remaining stable.
        rsz_writer.write_struct("<II", 0, 0)
        for spec in self.instances[1:]:
            if spec is None:
                continue
            rsz_writer.write_struct("<II", spec.class_hash, spec.class_def.crc)
        rsz_writer.pad_to(data_offset)
        rsz_writer.write(bytes(data_writer.data))

        usr_writer = BinaryWriter()
        # Apply RE Engine alignment and offset rules before touching binary fields;
        # later table offsets assume this layout.
        usr_writer.write_struct("<IiiiQQQ", self.user_magic, 0, 0, 0, 0x30, 0x30, 0x30)
        usr_writer.write(b"\x00" * 8)
        usr_writer.write(bytes(rsz_writer.data))
        return bytes(usr_writer.data)

    def _write_instance(self, writer: BinaryWriter, spec: InstanceSpec) -> None:
        """Write instance.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            spec (InstanceSpec): Planned instance specification used by the binary writer.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        for field_def in spec.class_def.fields:
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            writer.align(4 if field_def.is_array else max(field_def.align, 1))
            key = field_def.name or "unnamed"
            self._write_field(writer, field_def, spec.fields.get(key))

    def _write_field(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Write field.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            field_def (FieldDef): Schema field definition for the value being parsed or written.
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
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
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
                self._write_scalar(writer, non_array, item)
            return
        self._write_scalar(writer, field_def, value)

    def _write_scalar(
        self, writer: BinaryWriter, field_def: FieldDef, value: Any
    ) -> None:
        """Write scalar.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            field_def (FieldDef): Schema field definition for the value being parsed or written.
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
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
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            ref_id = (
                value.index
                if isinstance(value, InstanceRef)
                else self._coerce_int(value, field_def)
            )
            writer.write_struct("<i", ref_id)
            return
        if t in {"String", "Resource"}:
            # Decode strings and GUID-like values conservatively so invalid data does
            # not corrupt subsequent parsing.
            writer.align(4)
            raw = f"{value or ''}\x00".encode("utf-16-le")
            writer.write_struct("<I", len(raw) // 2)
            writer.write(raw)
            return
        if t == "C8":
            # C8 strings store UTF-8 byte length and keep a trailing null byte in the binary stream.
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
            # Vector and matrix fields write float32 components and pad missing values with zero.
            values = value if isinstance(value, list) else []
            count = max(field_def.size // 4, 1)
            for i in range(count):
                writer.write_struct("<f", float(values[i]) if i < len(values) else 0.0)
            return
        if isinstance(value, dict) and isinstance(value.get("raw"), str):
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            writer.write(bytes.fromhex(value["raw"]))
            return
        # Follow schema field layout exactly so alignment, padding, and unknown data
        # remain binary-compatible.
        writer.write(b"\x00" * max(field_def.size, 0))

    def _write_struct(self, writer: BinaryWriter, value: Any) -> None:
        """Write struct.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            writer (BinaryWriter): Binary writer receiving the encoded RSZ or .user.3 bytes.
            value (Any): Value to parse, normalize, compare, or serialize.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
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
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            writer.write(b"\x00" * (value.declared_size - consumed))

    def _coerce_int(self, value: Any, field_def: FieldDef) -> int:
        """Coerce int.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            value (Any): Value to parse, normalize, compare, or serialize.
            field_def (FieldDef): Schema field definition for the value being parsed or written.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
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
                # Prefer the numeric value inside "[123] Name" labels when present
                # so enum text can round-trip to binary.
                return int(match.group(1))
            try:
                return int(text, 0)
            except ValueError:
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                enum_value = self._resolve_enum_member(text, field_def)
                if enum_value is not None:
                    return enum_value
        raise PackError(f"cannot convert {value!r} to int for field {field_def.name}")

    def _resolve_enum_member(self, text: str, field_def: FieldDef) -> int | None:
        """Resolve enum member.

        The method preserves RE Engine alignment, table offsets, and scalar encodings while
        writing the binary layout.

        Args:
            text (str): Text to normalize or parse.
            field_def (FieldDef): Schema field definition for the value being parsed or written.

        Returns:
            int | None: Resolved numeric value, or None when the source cannot be mapped.
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
