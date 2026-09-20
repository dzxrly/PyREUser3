import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pyreuser3.api import REUser3Converter
from pyreuser3.core import discover_user3_files, is_user3_source_path
from pyreuser3.export import User3Exporter
from pyreuser3.pack import User3Packer
from pyreuser3.usr_container import probe_usr_path
from pyreuser3.web.page import INDEX_HTML
from pyreuser3.web.runners import ConversionRunners


class User3VariantDiscoveryTests(unittest.TestCase):
    def test_directory_discovery_accepts_decorated_suffixes_and_skips_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected_names = {
                "plain.user.3",
                "platform.user.3.X64",
                "build.user.3.Win64.Release",
                "upper.USER.3.PC",
            }
            ignored_names = {
                "plain.user.3.json",
                "platform.user.3.X64.json",
                "repack.user.3.pack.json",
                "not-user3.bin",
            }
            for name in expected_names | ignored_names:
                (root / name).write_bytes(b"not a real container")

            discovered = discover_user3_files(root)
            self.assertEqual({path.name for path in discovered}, expected_names)
            self.assertEqual(
                {path.name for path in REUser3Converter._discover_user3_files(root)},
                expected_names,
            )

            exporter = object.__new__(User3Exporter)
            exporter.user3_root = root
            exporter._exclude_patterns = []
            self.assertEqual(
                {path.name for path in exporter._discover_user3_files()},
                expected_names,
            )

            probe = probe_usr_path(root)
            self.assertEqual(probe["total"], len(expected_names))
            self.assertEqual(probe["failed"], len(expected_names))

    def test_source_name_predicate_is_case_insensitive(self):
        self.assertTrue(is_user3_source_path("a.user.3"))
        self.assertTrue(is_user3_source_path("a.user.3.X64"))
        self.assertTrue(is_user3_source_path("a.USER.3.X64.Release"))
        self.assertFalse(is_user3_source_path("a.user.3.X64.json"))
        self.assertFalse(is_user3_source_path("a.user.3.pack.json"))
        self.assertFalse(is_user3_source_path("a.user.30"))

    def test_web_picker_advertises_standard_and_decorated_suffixes(self):
        self.assertIn("*.user.3 *.user.3.*", INDEX_HTML)

    def test_packer_restores_decorated_source_filename(self):
        packer = object.__new__(User3Packer)
        json_root = Path("json")
        output_root = Path("output")
        self.assertEqual(
            packer.output_path_for(
                json_root / "nested" / "asset.user.3.X64.pack.json",
                json_root,
                output_root,
            ),
            output_root / "nested" / "asset.user.3.X64",
        )

    def test_packer_discovers_decorated_repack_document_by_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            json_root = root / "json"
            output_root = root / "output"
            json_root.mkdir()
            source = json_root / "asset.user.3.X64.pack.json"
            source.write_text("{}", encoding="utf-8")

            packer = object.__new__(User3Packer)
            packer.schema_path = root / "schema.json"
            packer.pack_json_file = Mock(return_value=output_root / "asset.user.3.X64")
            with patch("pyreuser3.pack.base.BatchProgress") as progress_type:
                progress_type.return_value.__enter__.return_value = Mock()
                result = packer.pack_directory(json_root, output_root)

            self.assertEqual(result, {"total": 1, "success": 1, "failed": 0})
            packer.pack_json_file.assert_called_once_with(
                source,
                output_root / "asset.user.3.X64",
            )


class WebTreeDepthTests(unittest.TestCase):
    def test_web_depth_is_forwarded_logged_and_returned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "input.user.3.X64"
            schema_path = root / "rsz.json"
            il2cpp_path = root / "il2cpp_dump.json"
            output_path = root / "output"
            input_path.write_bytes(b"input")
            schema_path.write_text("{}", encoding="utf-8")
            il2cpp_path.write_text("{}", encoding="utf-8")
            payload = {
                "inputDir": str(input_path),
                "schemaPath": str(schema_path),
                "outputDir": str(output_path),
                "il2cppDumpPath": str(il2cpp_path),
                "treeDepth": "0x2",
            }
            logs: list[str] = []

            with patch("pyreuser3.export.User3Exporter") as exporter_type:
                exporter_type.return_value.run.return_value = {
                    "total": 1,
                    "success": 1,
                    "failed": 0,
                }
                result = ConversionRunners(root).run_export(payload, logs.append)

            exporter_type.assert_called_once()
            kwargs = exporter_type.call_args.kwargs
            self.assertEqual(kwargs["tree_depth"], 2)
            self.assertEqual(kwargs["json_format"], "readable")
            self.assertEqual(result["treeDepth"], 2)
            self.assertIn("Tree depth: 2", logs)

    def test_explicit_depth_changes_readable_reference_expansion(self):
        document = {
            "parsed_instances": [{}, {}, {}],
            "object_roots": [1],
            "instance_info_map": {
                1: {"class_name": "Root"},
                2: {"class_name": "Middle"},
                3: {"class_name": "Leaf"},
            },
            "idx_map": {
                1: {
                    "data": {
                        "_class": "Root",
                        "fields": {"child": {"ref_instance_id": 2}},
                    }
                },
                2: {
                    "data": {
                        "_class": "Middle",
                        "fields": {"child": {"ref_instance_id": 3}},
                    }
                },
                3: {"data": {"_class": "Leaf", "fields": {"value": 7}}},
            },
            "header_userdata_infos": [],
        }
        exporter = object.__new__(User3Exporter)
        exporter.enum_lookup = {}
        exporter._parse_user3_document = Mock(return_value=document)

        exporter.tree_depth = 0
        depth_zero = exporter._parse_user3(Path("input.user.3"))
        exporter.tree_depth = 2
        depth_two = exporter._parse_user3(Path("input.user.3"))

        self.assertEqual(
            depth_zero,
            [{"Root": {"child": {"ref_instance_id": 2}}}],
        )
        self.assertEqual(
            depth_two,
            [
                {
                    "Root": {
                        "child": {
                            "Middle": {"child": {"Leaf": {"value": 7}}}
                        }
                    }
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
