import json
import tempfile
import unittest
from pathlib import Path

from pyreuser3.export.enums import ExporterEnumSourceMixin
from pyreuser3.export.postprocess import ExporterPostprocessMixin


class EnumPostprocessor(ExporterPostprocessMixin):
    def __init__(self):
        self.enum_lookup = {
            "via.ColorRampInterpolation": {
                0: ("Linear", 0),
                1: ("SmoothStep", 1),
            }
        }
        self.class_field_fixed_types = {
            "via.ColorRampKey": {
                "v2_Interpolation": "via.ColorRampInterpolation",
            }
        }
        self.serializable_to_fixed = {}
        self.generic_container_rules = {}
        self.generic_scalar_rules = {}
        self.bitset_rules = {}
        self.param_type_default_enum = {}
        self.enum_underlying_types = {"via.ColorRampInterpolation": "S32"}
        self.enum_flags = set()

    @staticmethod
    def _to_s32(value: int) -> int:
        u32 = value & 0xFFFFFFFF
        return u32 if u32 < 0x80000000 else u32 - 0x100000000

    @staticmethod
    def _to_u32(value: int) -> int:
        return value & 0xFFFFFFFF

    @staticmethod
    def _id_formatter(key: str, value: int) -> str:
        return f"[{value}] {key}"


class ExporterEnumSourceMixinTests(unittest.TestCase):
    def test_postprocess_formats_plain_schema_enum(self):
        postprocessor = EnumPostprocessor()

        self.assertEqual(
            postprocessor._postprocess_enum_nodes(
                {"v2_Interpolation": 1},
                current_class="via.ColorRampKey",
            ),
            {"v2_Interpolation": "[1] SmoothStep"},
        )

        self.assertEqual(
            postprocessor._postprocess_enum_nodes(
                {"v2_Interpolation": 99},
                current_class="via.ColorRampKey",
            ),
            {"v2_Interpolation": 99},
        )

    def test_postprocess_respects_unsigned_fixed_storage(self):
        postprocessor = EnumPostprocessor()
        fixed_type = "app.FieldDef.STAGE_Fixed"
        postprocessor.enum_lookup[fixed_type] = {
            3068809728: ("ST101", 3068809728),
        }
        postprocessor.enum_underlying_types[fixed_type] = "U32"
        postprocessor.class_field_fixed_types = {
            "app.user_data.GrassCullingSetting.cStageData": {
                "_StageID_Fixed": fixed_type,
            }
        }

        self.assertEqual(
            postprocessor._postprocess_enum_nodes(
                {"_StageID_Fixed": -1226157568},
                current_class="app.user_data.GrassCullingSetting.cStageData",
            ),
            {"_StageID_Fixed": "[3068809728] ST101"},
        )

    def test_postprocess_displays_signed_runtime_fixed_id(self):
        postprocessor = EnumPostprocessor()
        fixed_type = "app.FieldDef.STAGE_Fixed"
        postprocessor.enum_lookup[fixed_type] = {
            3068809728: ("ST101", 3068809728),
        }
        postprocessor.enum_underlying_types[fixed_type] = "S32"
        postprocessor.class_field_fixed_types = {
            "app.user_data.GrassCullingSetting.cStageData": {
                "_StageID_Fixed": fixed_type,
            }
        }

        self.assertEqual(
            postprocessor._postprocess_enum_nodes(
                {"_StageID_Fixed": -1226157568},
                current_class="app.user_data.GrassCullingSetting.cStageData",
            ),
            {"_StageID_Fixed": "[-1226157568] ST101"},
        )

    def test_repack_keeps_canonical_unsigned_fixed_id(self):
        postprocessor = EnumPostprocessor()
        fixed_type = "app.FieldDef.STAGE_Fixed"
        postprocessor.enum_lookup[fixed_type] = {
            3068809728: ("ST101", 3068809728),
        }
        postprocessor.enum_underlying_types[fixed_type] = "S32"
        postprocessor.class_field_fixed_types = {
            "app.user_data.GrassCullingSetting.cStageData": {
                "_StageID_Fixed": fixed_type,
            }
        }

        self.assertEqual(
            postprocessor._postprocess_enum_nodes(
                {"_StageID_Fixed": -1226157568},
                current_class="app.user_data.GrassCullingSetting.cStageData",
                output_mode="repack",
            ),
            {"_StageID_Fixed": "[3068809728] ST101"},
        )

    def test_unsigned_fixed_type_keeps_unknown_value_as_structured_label(self):
        postprocessor = EnumPostprocessor()
        fixed_type = "app.FieldDef.STAGE_Fixed"
        postprocessor.enum_lookup[fixed_type] = {
            3068809728: ("ST101", 3068809728),
        }
        postprocessor.enum_underlying_types[fixed_type] = "U32"

        self.assertEqual(
            postprocessor._format_enum_value(fixed_type, -1),
            "[4294967295] <unknown>",
        )

    def test_signed_fixed_enum_unknown_value_uses_runtime_fixed_id(self):
        postprocessor = EnumPostprocessor()
        fixed_type = "app.StageDef.StageID_Fixed"
        postprocessor.enum_lookup[fixed_type] = {
            884165440: ("st200", 884165440),
        }
        postprocessor.enum_underlying_types[fixed_type] = "S32"

        self.assertEqual(
            postprocessor._format_enum_value(fixed_type, -521343680),
            "[-521343680] <unknown>",
        )

    def test_export_enums_internal_skips_incomplete_enum_entries(self):
        dump = {
            "app.Mode_Fixed": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.Int32"},
                    "None": {"default": 0},
                    "Enabled": {"default": "0x1"},
                },
            },
            "app.Broken_Fixed": {
                "parent": "System.Enum",
            },
        }

        self.assertEqual(
            ExporterEnumSourceMixin.export_enums_internal(dump),
            {"app.Mode_Fixed": {"None": 0, "Enabled": 1}},
        )

    def test_export_enum_context_uses_non_rsz_metadata(self):
        dump = {
            "app.Mode_Fixed": {
                "parent": "System.Enum",
                "fields": {"A": {"default": 0}, "B": {"default": 1}},
            },
            "app.Mode_Serializable": {
                "methods": {},
                "parent": "System.Object",
            },
            "app.Owner": {
                "fields": {
                    "mode": {"type": "app.Mode_Fixed"},
                    "<backingMode>i__Field": {"type": "app.Mode_Fixed"},
                },
                "reflection_properties": {
                    "reflectedMode": {"type": "app.Mode_Fixed"},
                },
                "properties": {
                    "getterMode": {"getter": "get_getterMode", "setter": ""},
                    "setterMode": {"getter": "", "setter": "set_setterMode"},
                },
                "methods": {
                    "get_getterMode123": {
                        "returns": {"type": "app.Mode_Fixed"},
                    },
                    "set_setterMode124": {
                        "params": [{"type": "app.Mode_Fixed"}],
                        "returns": {"type": "System.Void"},
                    },
                },
            },
            "app.LegacyOwner": {
                "RSZ": [
                    {
                        "potential_name": "legacyMode",
                        "type": "app.Mode_Fixed",
                    }
                ],
            },
            "app.Container`2<app.Param,app.Mode_Fixed>": {
                "generic_arg_types": [
                    {"type": "app.Param"},
                    {"type": "app.Mode_Fixed"},
                ]
            },
        }

        context = ExporterEnumSourceMixin.export_enum_context_internal(dump)

        self.assertEqual(
            context["class_field_fixed_types"]["app.Owner"],
            {
                "mode": "app.Mode_Fixed",
                "<backingMode>i__Field": "app.Mode_Fixed",
                "backingMode": "app.Mode_Fixed",
                "reflectedMode": "app.Mode_Fixed",
                "getterMode": "app.Mode_Fixed",
                "setterMode": "app.Mode_Fixed",
            },
        )
        self.assertEqual(
            context["class_field_fixed_types"]["app.LegacyOwner"],
            {"legacyMode": "app.Mode_Fixed"},
        )
        self.assertEqual(
            context["serializable_to_fixed"],
            {"app.Mode_Serializable": "app.Mode_Fixed"},
        )
        self.assertEqual(
            context["generic_container_rules"],
            {
                "app.Container`2<app.Param,app.Mode_Fixed>": {
                    "param_type": "app.Param",
                    "enum_type": "app.Mode_Fixed",
                }
            },
        )

    def test_enum_context_infers_integer_fixed_backing_field_from_getter(self):
        dump = {
            "app.FieldDef.STAGE": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.Int32"},
                    "ST101": {"default": 0},
                },
            },
            "app.FieldDef.STAGE_Fixed": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.UInt32"},
                    "ST101": {"default": 3068809728},
                },
            },
            "app.user_data.GrassCullingSetting.cStageData": {
                "fields": {
                    "_StageID_Fixed": {"type": "System.Int32"},
                },
                "RSZ": [
                    {
                        "potential_name": "_StageID_Fixed",
                        "type": "System.Int32",
                    }
                ],
                "methods": {
                    "get_StageID1185265": {
                        "returns": {"type": "app.FieldDef.STAGE"},
                    }
                },
            },
        }

        context = ExporterEnumSourceMixin.export_enum_context_internal(dump)

        self.assertEqual(
            context["class_field_fixed_types"][
                "app.user_data.GrassCullingSetting.cStageData"
            ],
            {"_StageID_Fixed": "app.FieldDef.STAGE_Fixed"},
        )

    def test_enum_context_does_not_guess_fixed_type_without_enum_pair(self):
        dump = {
            "app.FieldDef.STAGE": {
                "parent": "System.Enum",
                "fields": {"ST101": {"default": 0}},
            },
            "app.Owner": {
                "fields": {"_StageID_Fixed": {"type": "System.Int32"}},
                "methods": {
                    "get_StageID1": {
                        "returns": {"type": "app.FieldDef.STAGE"},
                    }
                },
            },
        }

        context = ExporterEnumSourceMixin.export_enum_context_internal(dump)

        self.assertNotIn("app.Owner", context["class_field_fixed_types"])

    def test_enum_context_infers_integer_backing_field_from_fixed_getter(self):
        dump = {
            "app.StageDef.StageID_Fixed": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.UInt32"},
                    "st100": {"default": 1769129856},
                },
            },
            "app.user_data.WindGlobalAnimationData.cData": {
                "fields": {
                    "_StageID_Fixed": {"type": "System.Int32"},
                },
                "methods": {
                    "get_StageID_Fixed332574": {
                        "returns": {"type": "app.StageDef.StageID_Fixed"},
                    }
                },
            },
        }

        context = ExporterEnumSourceMixin.export_enum_context_internal(dump)

        self.assertEqual(
            context["class_field_fixed_types"][
                "app.user_data.WindGlobalAnimationData.cData"
            ]["_StageID_Fixed"],
            "app.StageDef.StageID_Fixed",
        )

    def test_enum_context_preserves_digits_from_explicit_property_name(self):
        dump = {
            "app.LOD": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.Int32"},
                    "LOD0": {"default": 0},
                },
            },
            "app.LOD_Fixed": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.Int32"},
                    "LOD0": {"default": 123},
                },
            },
            "app.Owner": {
                "fields": {
                    "_LOD0_Fixed": {"type": "System.Int32"},
                },
                "properties": {
                    "LOD0": {"getter": "get_LOD0"},
                },
                "methods": {
                    "get_LOD0123456": {
                        "returns": {"type": "app.LOD"},
                    }
                },
            },
        }

        context = ExporterEnumSourceMixin.export_enum_context_internal(dump)

        self.assertEqual(
            context["class_field_fixed_types"]["app.Owner"]["_LOD0_Fixed"],
            "app.LOD_Fixed",
        )

    def test_generic_context_supports_ordinary_enum_wrappers(self):
        dump = {
            "app.Mode": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.UInt32"},
                    "A": {"default": 0},
                    "B": {"default": 1},
                },
            },
            "app.Param": {"parent": "System.Object"},
            "ace.Bitset`1<app.Mode>": {
                "generic_arg_types": [{"type": "app.Mode"}],
            },
            "ace.btable.cEditFieldEnum`1<app.Mode>": {
                "generic_arg_types": [{"type": "app.Mode"}],
            },
            "app.cEnumerableParam`2<app.Mode,app.Param>": {
                "generic_arg_types": [
                    {"type": "app.Mode"},
                    {"type": "app.Param"},
                ],
            },
        }

        context = ExporterEnumSourceMixin.export_enum_context_internal(dump)

        self.assertEqual(context["bitset_rules"], {"ace.Bitset`1<app.Mode>": "app.Mode"})
        self.assertEqual(
            context["generic_scalar_rules"],
            {"ace.btable.cEditFieldEnum`1<app.Mode>": "app.Mode"},
        )
        self.assertEqual(
            context["generic_container_rules"],
            {
                "app.cEnumerableParam`2<app.Mode,app.Param>": {
                    "param_type": "app.Param",
                    "enum_type": "app.Mode",
                }
            },
        )

    def test_export_il2cpp_metadata_from_path_matches_in_memory_helpers(self):
        dump = {
            "app.Mode_Fixed": {
                "parent": "System.Enum",
                "fields": {"A": {"default": 0}, "B": {"default": 1}},
            },
            "via.motion.AxisDirection": {
                "parent": "System.Enum",
                "fields": {
                    "value__": {"type": "System.Byte"},
                    "Right": {"default": 2},
                },
            },
            "app.Owner": {
                "fields": {
                    "mode": {"type": "app.Mode_Fixed"},
                },
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            dump_path = Path(temp_dir) / "il2cpp_dump.json"
            dump_path.write_text(json.dumps(dump, indent=2), encoding="utf-8")

            enums_internal, enum_context = (
                ExporterEnumSourceMixin.export_il2cpp_metadata_from_path(dump_path)
            )

        self.assertEqual(
            enums_internal,
            ExporterEnumSourceMixin.export_enums_internal(dump),
        )
        self.assertEqual(
            enum_context,
            ExporterEnumSourceMixin.export_enum_context_internal(dump),
        )
        self.assertEqual(
            enum_context["enum_underlying_types"]["via.motion.AxisDirection"],
            "U8",
        )


if __name__ == "__main__":
    unittest.main()
