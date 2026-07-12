import unittest

from pyreuser3.core import PACK_JSON_FORMAT, PACK_JSON_FORMAT_V1
from pyreuser3.enum_codec import (
    decode_bitset,
    decode_flags,
    encode_bitset,
    encode_flags,
    enum_member_for_value,
    is_probable_flags_enum,
)
from pyreuser3.export.postprocess import ExporterPostprocessMixin
from pyreuser3.pack.plan import PackerPlanMixin
from pyreuser3.schema import ClassDef, FieldDef


class CodecPostprocessor(ExporterPostprocessMixin):
    def __init__(self):
        self.enum_lookup = {
            "app.Platform": {
                0: ("None", 0),
                1: ("PS5", 1),
                2: ("XBS", 2),
                8: ("STM", 8),
            },
            "app.Mask": {
                0: ("NONE", 0),
                2: ("ANGRY", 2),
                64: ("UNIQUE_03", 64),
            },
        }
        self.enum_underlying_types = {"app.Platform": "U32", "app.Mask": "U64"}
        self.enum_flags = {"app.Mask"}
        self.class_field_fixed_types = {"app.Owner": {"Mask": "app.Mask"}}
        self.serializable_to_fixed = {}
        self.generic_container_rules = {}
        self.generic_scalar_rules = {
            "ace.btable.cEditFieldEnum`1<app.Platform>": "app.Platform"
        }
        self.bitset_rules = {"ace.Bitset`1<app.Platform>": "app.Platform"}
        self.param_type_default_enum = {}
        self.enum_member_to_types = {}

    @staticmethod
    def _id_formatter(key, value):
        return f"[{value}] {key}"

    def _infer_enum_type_from_member_and_value(self, member_name, value):
        return None


class CodecPlan(PackerPlanMixin):
    def __init__(self):
        self.enum_lookup = {
            "app.Platform": {1: ("PS5", 1), 2: ("XBS", 2), 8: ("STM", 8)},
            "app.Mask": {2: ("ANGRY", 2), 64: ("UNIQUE_03", 64)},
        }
        self.member_lookup = {
            "app.Platform": {"PS5": 1, "XBS": 2, "STM": 8},
            "app.Mask": {"ANGRY": 2, "UNIQUE_03": 64},
        }
        self.bitset_rules = {"ace.Bitset`1<app.Platform>": "app.Platform"}
        self.enum_flags = {"app.Mask"}
        self.class_default_enums = {"ace.btable.cEditFieldEnum`1<app.Mask>": "app.Mask"}


class EnumCodecTests(unittest.TestCase):
    def test_width_aware_lookup_does_not_create_u32_alias_for_u64(self):
        lookup = {"app.Wide": {0: ("ZERO", 0), 1 << 63: ("HIGH", 1 << 63)}}
        self.assertEqual(
            enum_member_for_value(lookup, "app.Wide", 1 << 63, {"app.Wide": "U64"}),
            ("HIGH", 1 << 63),
        )
        self.assertIsNone(
            enum_member_for_value(lookup, "app.Wide", 0x80000000, {"app.Wide": "U64"})
        )

    def test_bitset_codec_preserves_unknown_bits_and_word_count(self):
        lookup = {"app.Platform": {1: ("PS5", 1), 8: ("STM", 8)}}
        labels = decode_bitset([0x102, 0x20], "app.Platform", lookup, 32)
        self.assertEqual(labels, ["[1] PS5", "[8] STM", "[37] <unknown>"])
        self.assertEqual(
            encode_bitset(labels, "app.Platform", {"app.Platform": {}}, 32, 2),
            [0x102, 0x20],
        )
        self.assertEqual(
            encode_bitset([], "app.Platform", {"app.Platform": {}}, 32, 0),
            [],
        )

    def test_readable_and_repack_bitset_shapes(self):
        post = CodecPostprocessor()
        raw = {
            "ace.Bitset`1<app.Platform>": {
                "_Value": [262],
                "_MaxElement": 32,
            }
        }
        self.assertEqual(
            post._postprocess_enum_nodes(raw),
            {
                "app.Platform": ["[1] PS5", "[2] XBS", "[8] STM"],
                "_MaxElement": 32,
                "_WordCount": 1,
            },
        )
        self.assertEqual(
            post._postprocess_enum_nodes(
                raw["ace.Bitset`1<app.Platform>"],
                current_class="ace.Bitset`1<app.Platform>",
                output_mode="repack",
            )["_Value"],
            ["[1] PS5", "[2] XBS", "[8] STM"],
        )

    def test_cedit_wrapper_collapses_to_enum_label(self):
        post = CodecPostprocessor()
        converted = post._postprocess_enum_nodes(
            {"ace.btable.cEditFieldEnum`1<app.Platform>": {"value": 2}}
        )
        self.assertEqual(post._finalize_export_tree(converted), "[2] XBS")

    def test_scalar_flags_expand_and_combine(self):
        post = CodecPostprocessor()
        self.assertEqual(
            post._postprocess_enum_nodes({"Mask": 66}, current_class="app.Owner"),
            {"Mask": ["[2] ANGRY", "[64] UNIQUE_03"]},
        )
        self.assertEqual(
            decode_flags(post.enum_lookup, "app.Mask", 66, post.enum_underlying_types),
            ["[2] ANGRY", "[64] UNIQUE_03"],
        )
        self.assertEqual(
            encode_flags(
                ["[2] ANGRY", "UNIQUE_03"],
                "app.Mask",
                {"app.Mask": {"UNIQUE_03": 64}},
            ),
            66,
        )
        self.assertTrue(
            is_probable_flags_enum(
                "app.WIDE_FLAG",
                {
                    1: ("A", 1),
                    2: ("B", 2),
                    3: ("ALL", 3),
                    1 << 63: ("HIGH", 1 << 63),
                },
                "U64",
            )
        )

    def test_plan_normalizes_bitset_v2_and_scalar_flags(self):
        plan = CodecPlan()
        bitset_class = ClassDef(
            name="ace.Bitset`1<app.Platform>",
            crc=1,
            fields=[
                FieldDef("_Value", "U32", "System.UInt32", 4, 4, True),
                FieldDef("_MaxElement", "S32", "System.Int32", 4, 4, False),
            ],
        )
        normalized = plan._normalize_bitset_fields(
            bitset_class,
            {
                "_Value": ["[1] PS5", "[8] STM"],
                "_MaxElement": 32,
                "_WordCount": 1,
            },
        )
        self.assertEqual(normalized, {"_Value": [258], "_MaxElement": 32})

        flag_field = FieldDef("Mask", "U64", "app.Mask", 8, 8, False)
        self.assertEqual(
            plan._prepare_field_value(flag_field, ["[2] ANGRY", "[64] UNIQUE_03"]),
            66,
        )

        cedit_class = ClassDef(
            name="ace.btable.cEditFieldEnum`1<app.Mask>",
            crc=2,
            fields=[FieldDef("_Value", "S32", "System.Int32", 4, 4, False)],
        )
        self.assertEqual(
            plan._prepare_fields(
                cedit_class,
                {"_Value": ["[2] ANGRY", "[64] UNIQUE_03"]},
            ),
            {"_Value": 66},
        )

    def test_pack_v1_and_v2_documents_are_recognized(self):
        plan = CodecPlan()
        for format_name in (PACK_JSON_FORMAT_V1, PACK_JSON_FORMAT):
            self.assertTrue(plan._is_pack_document({"_format": format_name, "_instances": {}}))


if __name__ == "__main__":
    unittest.main()
