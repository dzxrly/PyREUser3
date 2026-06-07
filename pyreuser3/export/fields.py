"""Field parsing helpers for RE_RSZ instance data."""

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
    """Mixin for parsing fields from RSZ instance data."""

    def _parse_scalar(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """Internal helper for parse scalar."""
        t = field.field_type
        # Keep this implementation detail explicit.
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
            # Keep instance references stable while parsing or packing data.
            return {"ref_instance_id": reader.read_s32()}
        if t in ("String", "Resource"):
            return read_len_utf16(reader)
        if t == "C8":
            return read_len_c8(reader)
        if t in ("Guid", "GameObjectRef", "Uri"):
            return read_guid_like(reader)
        if t == "Struct":
            if depth >= 4:
                # Preserve field layout details for binary compatibility.
                to_read = max(0, min(field.size, reader.size - reader.tell()))
                return {"raw": reader.read(to_read).hex(), "truncated": True}
            struct_hash = self.typedb.resolve_struct_hash(field.original_type)
            if struct_hash is None:
                # Preserve field layout details for binary compatibility.
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
                # Preserve field layout details for binary compatibility.
                reader.seek(
                    align(reader.tell(), 4 if sf.is_array else max(sf.align, 1))
                )
                out[sf.name or "unnamed"] = self._parse_field_value(
                    reader, sf, depth=depth + 1
                )
            consumed = reader.tell() - start
            if field.size > consumed:
                # Preserve field layout details for binary compatibility.
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
            # Keep this implementation detail explicit.
            count = max(field.size // 4, 1)
            return [reader.read_f32() for _ in range(count)]

        if field.size <= 0:
            return None
        to_read = max(0, min(field.size, reader.size - reader.tell()))
        # Keep this implementation detail explicit.
        return {"raw": reader.read(to_read).hex(), "type": t}

    def _parse_field_value(
        self, reader: BinaryReader, field: FieldDef, depth: int = 0
    ) -> Any:
        """Internal helper for parse field value."""
        if field.is_array:
            count = reader.read_u32()
            if count > 1_000_000:
                # Keep this implementation detail explicit.
                return []
            items = []
            for _ in range(count):
                if reader.tell() >= reader.size:
                    break
                reader.seek(align(reader.tell(), max(field.align, 1)))
                # Preserve field layout details for binary compatibility.
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
        """Internal helper for estimate min instance size."""
        pos = 0
        for field in cls.fields:
            # Record per-file failures without stopping the whole batch.
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
        """Internal helper for parse instance."""
        cls = self.typedb.get_class(class_hash)
        if cls is None:
            raise ParseError(f"class hash 0x{class_hash:08x} not found in schema")
        out: dict[str, Any] = {"_class": cls.name, "fields": {}}
        for field in cls.fields:
            # Preserve field layout details for binary compatibility.
            reader.seek(
                align(reader.tell(), 4 if field.is_array else max(field.align, 1))
            )
            out["fields"][field.name or "unnamed"] = self._parse_field_value(
                reader, field, depth=0
            )
        return out
