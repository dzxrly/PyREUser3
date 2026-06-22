"""Parse RSZ scalar, array, object-reference, and struct fields according to schema metadata.

The parser preserves raw bytes for unsupported or uncertain layouts so exported JSON
remains useful even when templates are incomplete.
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
    enum_storage_size,
    enum_storage_type_from_size,
)
from ..schema import ClassDef, FieldDef


class ExporterFieldParserMixin:
    """Read scalar, array, object-reference, and struct field values according to RE_RSZ schema
    metadata.
    """

    def _parse_scalar(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """Parse scalar.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            reader (BinaryReader): BinaryReader positioned at the value to parse.
            field (FieldDef): Schema field definition for the value being parsed or written.
            depth (int): Remaining recursive expansion depth for reference traversal.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        t = field.field_type
        # Primitive numeric field types map directly to little-endian binary reads.
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
            return self._read_enum_value(reader, field)
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
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            return {"ref_instance_id": reader.read_s32()}
        if t in ("String", "Resource"):
            return read_len_utf16(reader)
        if t == "C8":
            return read_len_c8(reader)
        if t in ("Guid", "GameObjectRef", "Uri"):
            return read_guid_like(reader)
        if t == "Struct":
            if depth >= 4:
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {"raw": reader.read(to_read).hex(), "truncated": True}
            struct_hash = self.typedb.resolve_struct_hash(field.original_type)
            if struct_hash is None:
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
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
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
                reader.seek(
                    align(reader.tell(), 4 if sf.is_array else max(sf.align, 1))
                )
                out[sf.name or "unnamed"] = self._parse_field_value(
                    reader, sf, depth=depth + 1
                )
            consumed = reader.tell() - start
            if field.size > consumed:
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
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
            # Vector and matrix fields are stored as contiguous float32 components;
            # the declared field size determines the component count.
            count = max(field.size // 4, 1)
            return [reader.read_f32() for _ in range(count)]

        if field.size <= 0:
            return None
        to_read = max(0, min(field.size, reader.size - reader.tell()))
        # Preserve unrecognized field bytes as hex so unsupported layouts remain
        # inspectable instead of silently discarding data.
        return {"raw": reader.read(to_read).hex(), "type": t}

    def _enum_storage_type_for_field(self, field: FieldDef) -> str:
        """Resolve the binary storage type used by an enum field."""
        resolver = getattr(self, "_resolve_enum_storage_type", None)
        if callable(resolver):
            return resolver(field)
        return enum_storage_type_from_size(field.size)

    def _read_enum_value(self, reader: BinaryReader, field: FieldDef) -> int:
        """Read an enum using its il2cpp underlying type or schema-declared width."""
        storage_type = self._enum_storage_type_for_field(field)
        if storage_type == "S8":
            return reader.read_s8()
        if storage_type == "U8":
            return reader.read_u8()
        if storage_type == "S16":
            return reader.read_s16()
        if storage_type == "U16":
            return reader.read_u16()
        if storage_type == "U32":
            return reader.read_u32()
        if storage_type == "S64":
            return reader.read_s64()
        if storage_type == "U64":
            return reader.read_u64()
        return reader.read_s32()

    def _parse_field_value(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """Parse field value.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            reader (BinaryReader): BinaryReader positioned at the value to parse.
            field (FieldDef): Schema field definition for the value being parsed or written.
            depth (int): Remaining recursive expansion depth for reference traversal.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        if field.is_array:
            count = reader.read_u32()
            if count > 1_000_000:
                # Treat impossible array lengths as cursor or template corruption
                # and return an empty array rather than reading arbitrary memory.
                return []
            items = []
            for _ in range(count):
                if reader.tell() >= reader.size:
                    break
                reader.seek(align(reader.tell(), max(field.align, 1)))
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
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
        """Estimate the smallest binary size required for a parsed instance layout.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        pos = 0
        for field in cls.fields:
            # Treat each file independently so one malformed resource is reported but
            # does not stop the rest of the batch.
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
            elif t == "Enum":
                pos += enum_storage_size(self._enum_storage_type_for_field(field))
            elif t in ("S32", "U32", "Sfix", "F32"):
                pos += 4
            elif t in ("S64", "U64", "F64"):
                pos += 8
            else:
                pos += max(field.size, 0)
        return max(pos, 1)

    def _parse_instance(self, reader: BinaryReader, class_hash: int) -> dict[str, Any]:
        """Parse instance.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            reader (BinaryReader): BinaryReader positioned at the value to parse.
            class_hash (int): RE_RSZ type hash for a class.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.

        Raises:
            ParseError: Binary data did not match the expected .user.3 or RSZ layout.
        """
        cls = self.typedb.get_class(class_hash)
        if cls is None:
            raise ParseError(f"class hash 0x{class_hash:08x} not found in schema")
        out: dict[str, Any] = {"_class": cls.name, "fields": {}}
        for field in cls.fields:
            # Follow schema field layout exactly so alignment, padding, and unknown data
            # remain binary-compatible.
            reader.seek(
                align(reader.tell(), 4 if field.is_array else max(field.align, 1))
            )
            out["fields"][field.name or "unnamed"] = self._parse_field_value(
                reader, field, depth=0
            )
        return out
