import copy
import json
import math
import struct
import tempfile
import unittest
from pathlib import Path

from pyreuser3.core import BinaryReader
from pyreuser3.export.enums import ExporterEnumSourceMixin
from pyreuser3.export.fields import ExporterFieldParserMixin
from pyreuser3.native_structs import (
    NATIVE_STRUCT_CODECS,
    collect_validated_native_struct_layout,
    encode_native_struct,
    normalize_native_struct_layouts,
)
from pyreuser3.pack.models import BinaryWriter, NativeStructValue, PackError
from pyreuser3.pack.values import PackerValueMixin
from pyreuser3.pack.writer import PackerWriterMixin
from pyreuser3.schema import FieldDef


def make_il2cpp_entry(codec, *, include_flags=True):
    fields = {
        member.name: {
            "type": member.type_name,
            "offset_from_fieldptr": f"0x{member.offset:x}",
        }
        for member in codec.layout_members
    }
    fields["Zero"] = {
        "type": codec.il2cpp_type,
        "offset_from_fieldptr": "0x0",
    }
    entry = {
        "parent": "System.ValueType",
        "size": f"{codec.boxed_size:x}",
        "fields": fields,
    }
    if include_flags:
        entry["flags"] = "Public | SequentialLayout | Sealed"
        for name, field in fields.items():
            field["flags"] = "Public | Static" if name == "Zero" else "Public"
    return entry


def validated_layouts():
    result = {}
    for codec in NATIVE_STRUCT_CODECS:
        item = collect_validated_native_struct_layout(
            codec.il2cpp_type, make_il2cpp_entry(codec)
        )
        if item is None:
            raise AssertionError(f"test fixture did not validate: {codec.codec_id}")
        type_name, descriptor = item
        result[type_name] = descriptor
    return result


def make_field(codec, *, is_array=False):
    return FieldDef(
        name="value",
        field_type=codec.schema_types[0],
        original_type=codec.il2cpp_type,
        size=codec.payload_size,
        align=16 if codec.il2cpp_type == "via.Sphere" else 4,
        is_array=is_array,
    )


class NativeStructHarness(
    ExporterFieldParserMixin, PackerValueMixin, PackerWriterMixin
):
    def __init__(self, layouts=None):
        self.native_struct_layouts = layouts or {}
        self.enum_lookup = {}
        self.member_lookup = {}
        self.enum_flags = set()


class NativeStructTests(unittest.TestCase):
    def test_registry_validates_all_five_layouts_with_or_without_flags(self):
        for codec in NATIVE_STRUCT_CODECS:
            with self.subTest(codec=codec.codec_id, flags="present"):
                item = collect_validated_native_struct_layout(
                    codec.il2cpp_type, make_il2cpp_entry(codec)
                )
                self.assertEqual(item, (codec.il2cpp_type, codec.descriptor()))
            with self.subTest(codec=codec.codec_id, flags="omitted"):
                item = collect_validated_native_struct_layout(
                    codec.il2cpp_type,
                    make_il2cpp_entry(codec, include_flags=False),
                )
                self.assertEqual(item, (codec.il2cpp_type, codec.descriptor()))

    def test_layout_validation_fails_closed_on_every_binary_contract(self):
        codec = NATIVE_STRUCT_CODECS[0]
        mutations = {}

        wrong_parent = make_il2cpp_entry(codec)
        wrong_parent["parent"] = "System.Object"
        mutations["parent"] = wrong_parent

        wrong_flags = make_il2cpp_entry(codec)
        wrong_flags["flags"] = "Public | AutoLayout"
        mutations["layout flags"] = wrong_flags

        wrong_size = make_il2cpp_entry(codec)
        wrong_size["size"] = "20"
        mutations["boxed size"] = wrong_size

        wrong_type = make_il2cpp_entry(codec)
        wrong_type["fields"]["x"]["type"] = "System.UInt32"
        mutations["member type"] = wrong_type

        wrong_offset = make_il2cpp_entry(codec)
        wrong_offset["fields"]["y"]["offset_from_fieldptr"] = "0x8"
        mutations["member offset"] = wrong_offset

        unexpected_field = make_il2cpp_entry(codec)
        unexpected_field["fields"]["z"] = {
            "type": "System.Int32",
            "offset_from_fieldptr": "0x8",
            "flags": "Public",
        }
        mutations["unexpected instance member"] = unexpected_field

        for label, entry in mutations.items():
            with self.subTest(contract=label):
                self.assertIsNone(
                    collect_validated_native_struct_layout(codec.il2cpp_type, entry)
                )

    def test_normalizer_rejects_tampered_cached_descriptors(self):
        layouts = validated_layouts()
        tampered = copy.deepcopy(layouts)
        first_type = NATIVE_STRUCT_CODECS[0].il2cpp_type
        tampered[first_type]["payload_size"] = 16

        normalized = normalize_native_struct_layouts(tampered)

        self.assertNotIn(first_type, normalized)
        self.assertEqual(len(normalized), len(NATIVE_STRUCT_CODECS) - 1)

    def test_single_stream_metadata_pass_collects_native_layouts(self):
        codec = NATIVE_STRUCT_CODECS[0]
        dump = {codec.il2cpp_type: make_il2cpp_entry(codec)}
        with tempfile.TemporaryDirectory() as temp_dir:
            dump_path = Path(temp_dir) / "il2cpp_dump.json"
            dump_path.write_text(json.dumps(dump), encoding="utf-8")

            enums, context = ExporterEnumSourceMixin.export_il2cpp_metadata_from_path(
                dump_path
            )

        self.assertEqual(enums, {})
        self.assertEqual(
            context["native_struct_layouts"],
            {codec.il2cpp_type: codec.descriptor()},
        )

    def test_scalar_decode_and_encode_are_symmetric_for_every_codec(self):
        values = {
            "via.Int2": ({"x": -7, "y": 42}, struct.pack("<ii", -7, 42)),
            "via.Uint2": (
                {"x": 7, "y": 4_000_000_000},
                struct.pack("<II", 7, 4_000_000_000),
            ),
            "via.Range": (
                {"s": -1.5, "r": 3.25},
                struct.pack("<ff", -1.5, 3.25),
            ),
            "via.RangeI": ({"s": -10, "r": 20}, struct.pack("<ii", -10, 20)),
            "via.Sphere": (
                {"pos": [1.0, -2.0, 3.5], "r": 4.25},
                struct.pack("<ffff", 1.0, -2.0, 3.5, 4.25),
            ),
        }
        layouts = validated_layouts()
        harness = NativeStructHarness(layouts)

        for codec in NATIVE_STRUCT_CODECS:
            value, expected_payload = values[codec.il2cpp_type]
            field = make_field(codec)
            with self.subTest(codec=codec.codec_id, operation="decode"):
                decoded = harness._parse_scalar(BinaryReader(expected_payload), field)
                self.assertEqual(decoded, value)
            with self.subTest(codec=codec.codec_id, operation="encode"):
                prepared = harness._prepare_field_value(field, value)
                self.assertIsInstance(prepared, NativeStructValue)
                writer = BinaryWriter()
                harness._write_scalar(writer, field, prepared)
                self.assertEqual(bytes(writer.data), expected_payload)
                self.assertEqual(encode_native_struct(codec, decoded), expected_payload)

    def test_scalar_falls_back_to_raw_without_a_validated_layout(self):
        codec = NATIVE_STRUCT_CODECS[0]
        field = make_field(codec)
        payload = struct.pack("<ii", -1, 2)

        value = NativeStructHarness()._parse_scalar(BinaryReader(payload), field)

        self.assertEqual(value, {"raw": payload.hex(), "type": "Int2"})

    def test_schema_signature_mismatch_falls_back_to_raw(self):
        codec = NATIVE_STRUCT_CODECS[0]
        layouts = validated_layouts()
        cases = (
            FieldDef("value", "Data", codec.il2cpp_type, 8, 4, False),
            FieldDef("value", "Int2", "app.NotInt2", 8, 4, False),
            FieldDef("value", "Int2", codec.il2cpp_type, 4, 4, False),
        )
        for field in cases:
            payload = bytes(range(field.size))
            with self.subTest(field=field):
                value = NativeStructHarness(layouts)._parse_scalar(
                    BinaryReader(payload), field
                )
                self.assertEqual(
                    value, {"raw": payload.hex(), "type": field.field_type}
                )

    def test_non_finite_float_falls_back_to_lossless_raw(self):
        codec = next(c for c in NATIVE_STRUCT_CODECS if c.il2cpp_type == "via.Range")
        field = make_field(codec)
        payload = struct.pack("<ff", math.nan, 1.0)

        value = NativeStructHarness(validated_layouts())._parse_scalar(
            BinaryReader(payload), field
        )

        self.assertEqual(value, {"raw": payload.hex(), "type": "Range"})

    def test_old_raw_scalar_json_packs_without_validated_metadata(self):
        codec = NATIVE_STRUCT_CODECS[0]
        field = make_field(codec)
        payload = struct.pack("<ii", 12, -9)
        harness = NativeStructHarness()

        prepared = harness._prepare_field_value(
            field, {"raw": payload.hex(), "type": field.field_type}
        )
        writer = BinaryWriter()
        harness._write_scalar(writer, field, prepared)

        self.assertEqual(bytes(writer.data), payload)

    def test_structured_json_requires_a_validated_layout(self):
        codec = NATIVE_STRUCT_CODECS[0]
        field = make_field(codec)

        with self.assertRaisesRegex(PackError, "active il2cpp dump did not validate"):
            NativeStructHarness()._prepare_field_value(field, {"x": 1, "y": 2})

    def test_malformed_structured_or_raw_json_is_rejected(self):
        uint_codec = next(
            c for c in NATIVE_STRUCT_CODECS if c.il2cpp_type == "via.Uint2"
        )
        field = make_field(uint_codec)
        harness = NativeStructHarness(validated_layouts())

        invalid_values = (
            {"x": 1},
            {"x": 1, "y": -1},
            {"x": True, "y": 1},
            {"raw": "00"},
            {"raw": "not hex"},
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(PackError):
                harness._prepare_field_value(field, value)

    def test_array_decode_encode_and_legacy_raw_items(self):
        codec = next(c for c in NATIVE_STRUCT_CODECS if c.il2cpp_type == "via.Range")
        field = make_field(codec, is_array=True)
        values = [{"s": 1.0, "r": 2.0}, {"s": -3.0, "r": 4.5}]
        expected = struct.pack("<Iffff", 2, 1.0, 2.0, -3.0, 4.5)
        harness = NativeStructHarness(validated_layouts())

        prepared = harness._prepare_field_value(field, values)
        writer = BinaryWriter()
        harness._write_field(writer, field, prepared)
        self.assertEqual(bytes(writer.data), expected)
        self.assertEqual(
            harness._parse_field_value(BinaryReader(expected), field), values
        )

        raw_items = [
            {"raw": struct.pack("<ff", 1.0, 2.0).hex(), "type": "Range"},
            {"raw": struct.pack("<ff", -3.0, 4.5).hex(), "type": "Range"},
        ]
        raw_harness = NativeStructHarness()
        raw_prepared = raw_harness._prepare_field_value(field, raw_items)
        raw_writer = BinaryWriter()
        raw_harness._write_field(raw_writer, field, raw_prepared)
        self.assertEqual(bytes(raw_writer.data), expected)

    def test_array_round_trip_covers_every_codec(self):
        values = {
            "via.Int2": [{"x": -1, "y": 2}, {"x": 3, "y": -4}],
            "via.Uint2": [{"x": 1, "y": 2}, {"x": 3, "y": 4_000_000_000}],
            "via.Range": [{"s": 1.0, "r": 2.0}, {"s": -3.0, "r": 4.5}],
            "via.RangeI": [{"s": -10, "r": 20}, {"s": 30, "r": 40}],
            "via.Sphere": [
                {"pos": [1.0, 2.0, 3.0], "r": 4.0},
                {"pos": [-1.0, -2.0, -3.0], "r": 5.0},
            ],
        }
        harness = NativeStructHarness(validated_layouts())

        for codec in NATIVE_STRUCT_CODECS:
            field = make_field(codec, is_array=True)
            items = values[codec.il2cpp_type]
            prepared = harness._prepare_field_value(field, items)
            writer = BinaryWriter()
            harness._write_field(writer, field, prepared)

            expected = bytearray(struct.pack("<I", len(items)))
            expected.extend(
                b"\x00" * ((-len(expected)) % max(field.align, 1))
            )
            for index, item in enumerate(items):
                if index:
                    expected.extend(
                        b"\x00" * ((-len(expected)) % max(field.align, 1))
                    )
                expected.extend(encode_native_struct(codec, item))

            with self.subTest(codec=codec.codec_id):
                self.assertEqual(bytes(writer.data), bytes(expected))
                self.assertEqual(
                    harness._parse_field_value(BinaryReader(bytes(expected)), field),
                    items,
                )


if __name__ == "__main__":
    unittest.main()
