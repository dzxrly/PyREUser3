import unittest

from pyreuser3.core import BinaryReader, RSZ_MAGIC, USR_MAGIC, enum_storage_type_from_size
from pyreuser3.export.fields import ExporterFieldParserMixin
from pyreuser3.pack.models import BinaryWriter
from pyreuser3.pack.writer import PackerWriterMixin
from pyreuser3.schema import FieldDef


class EnumFieldParser(ExporterFieldParserMixin):
    def __init__(self, storage_type: str | None = None):
        self.storage_type = storage_type

    def _resolve_enum_storage_type(self, field: FieldDef) -> str:
        return self.storage_type or enum_storage_type_from_size(field.size)


class EnumFieldWriter(PackerWriterMixin):
    def __init__(self):
        self.enum_underlying_types = {"via.motion.AxisDirection": "U8"}
        self.member_lookup = {"via.motion.AxisDirection": {"Right": 2}}

    @staticmethod
    def _to_s32(value: int) -> int:
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000


class EmptyBinaryWriter(PackerWriterMixin):
    def __init__(self):
        self.instances = [None]
        self.user_magic = USR_MAGIC
        self.rsz_magic = RSZ_MAGIC


class EnumBinaryTests(unittest.TestCase):
    def test_build_binary_uses_shared_alignment_helper(self):
        writer_mixin = EmptyBinaryWriter()

        data = writer_mixin._build_binary([])

        self.assertEqual(data[:4], USR_MAGIC.to_bytes(4, "little"))
        self.assertEqual(data[0x30:0x34], RSZ_MAGIC.to_bytes(4, "little"))

    def test_enum_reader_uses_schema_size_fallback(self):
        parser = EnumFieldParser()
        reader = BinaryReader(b"\x02abcdef")
        field = FieldDef(
            name="v2_LegDirection",
            field_type="Enum",
            original_type="via.motion.AxisDirection",
            size=1,
            align=1,
            is_array=False,
        )

        self.assertEqual(parser._parse_field_value(reader, field), 2)
        self.assertEqual(reader.tell(), 1)

    def test_enum_reader_uses_il2cpp_underlying_type(self):
        parser = EnumFieldParser("U8")
        reader = BinaryReader(b"\x02\x00\x00\x00")
        field = FieldDef(
            name="v2_LegDirection",
            field_type="Enum",
            original_type="via.motion.AxisDirection",
            size=4,
            align=4,
            is_array=False,
        )

        self.assertEqual(parser._parse_field_value(reader, field), 2)
        self.assertEqual(reader.tell(), 1)

    def test_enum_writer_uses_il2cpp_underlying_type_for_labels(self):
        writer_mixin = EnumFieldWriter()
        writer = BinaryWriter()
        field = FieldDef(
            name="v2_LegDirection",
            field_type="Enum",
            original_type="via.motion.AxisDirection",
            size=1,
            align=1,
            is_array=False,
        )

        writer_mixin._write_scalar(writer, field, "Right")
        self.assertEqual(bytes(writer.data), b"\x02")


if __name__ == "__main__":
    unittest.main()
