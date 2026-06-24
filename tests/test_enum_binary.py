import json
import tempfile
import unittest
from pathlib import Path

from pyreuser3.core import BinaryReader, RSZ_MAGIC, USR_MAGIC, enum_storage_type_from_size
from pyreuser3.export.fields import ExporterFieldParserMixin
from pyreuser3.pack.models import BinaryWriter
from pyreuser3.pack.plan import PackerPlanMixin
from pyreuser3.pack.writer import PackerWriterMixin
from pyreuser3.schema import FieldDef, TypeDB


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


class PlanDefaults(PackerPlanMixin):
    pass


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

    def test_runtime_type_reader_uses_c8_string_layout(self):
        parser = EnumFieldParser()
        reader = BinaryReader(b"\x04\x00\x00\x00abc\x00tail")
        field = FieldDef(
            name="_OrderType",
            field_type="RuntimeType",
            original_type="System.Type",
            size=4,
            align=4,
            is_array=False,
        )

        self.assertEqual(parser._parse_field_value(reader, field), "abc")
        self.assertEqual(reader.tell(), 8)

    def test_runtime_type_writer_uses_c8_string_layout(self):
        writer_mixin = EnumFieldWriter()
        writer = BinaryWriter()
        field = FieldDef(
            name="_OrderType",
            field_type="RuntimeType",
            original_type="System.Type",
            size=4,
            align=4,
            is_array=False,
        )

        writer_mixin._write_scalar(writer, field, "abc")

        self.assertEqual(bytes(writer.data), b"\x04\x00\x00\x00abc\x00")

    def test_runtime_type_default_is_empty_string(self):
        field = FieldDef(
            name="_OrderType",
            field_type="RuntimeType",
            original_type="System.Type",
            size=4,
            align=4,
            is_array=False,
        )

        self.assertEqual(PlanDefaults()._default_value(field), "")

    def test_typedb_selects_btable_order_list_crc_variant(self):
        schema = {
            "d081f6c1": {
                "crc": "15afce2d",
                "name": "ace.btable.user_data.BTableOrderList",
                "fields": [
                    {
                        "name": "_OperatorFactories",
                        "type": "Object",
                        "original_type": "ace.btable.cOperatorFactory",
                        "size": 4,
                        "align": 4,
                        "array": True,
                    },
                    {
                        "name": "_CommandFactories",
                        "type": "Object",
                        "original_type": "ace.btable.cCommandFactory",
                        "size": 4,
                        "align": 4,
                        "array": True,
                    },
                    {
                        "name": "_OperatorHashList",
                        "type": "U64",
                        "original_type": "System.UInt64",
                        "size": 8,
                        "align": 8,
                        "array": True,
                    },
                    {
                        "name": "_CommandHashList",
                        "type": "U64",
                        "original_type": "System.UInt64",
                        "size": 8,
                        "align": 8,
                        "array": True,
                    },
                ],
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_path = Path(tmpdir) / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            typedb = TypeDB.load(schema_path)

        current = typedb.get_class(0xD081F6C1, 0x15AFCE2D)
        legacy = typedb.get_class(0xD081F6C1, 0x6C85037C)
        resolved = typedb.get_class_for_fields(
            "ace.btable.user_data.BTableOrderList",
            field_names={"_OperatorFactories", "_CommandFactories"},
        )
        crc_alias = typedb.get_class_for_fields(
            "ace.btable.user_data.BTableOrderList",
            field_names={
                "_OperatorFactories",
                "_CommandFactories",
                "_OperatorHashList",
                "_CommandHashList",
            },
            crc=0x12345678,
        )

        self.assertIsNotNone(current)
        self.assertEqual(len(current.fields), 4)
        self.assertIsNotNone(legacy)
        self.assertEqual(legacy.crc, 0x6C85037C)
        self.assertEqual([field.name for field in legacy.fields], [
            "_OperatorFactories",
            "_CommandFactories",
        ])
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[1].crc, 0x6C85037C)
        self.assertIsNotNone(crc_alias)
        self.assertEqual(crc_alias[1].crc, 0x12345678)
        self.assertEqual(len(crc_alias[1].fields), 4)


if __name__ == "__main__":
    unittest.main()
