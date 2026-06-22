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
        self.param_type_default_enum = {}

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
