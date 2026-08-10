import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pyreuser3.api import REUser3Converter
from pyreuser3.export import User3Exporter
from pyreuser3.schema import TypeDB


class ConverterMetadataCacheTests(unittest.TestCase):
    def test_converter_reuses_and_invalidates_schema_and_il2cpp_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            schema = root / "schema.json"
            dump = root / "il2cpp_dump.json"
            schema.write_text("{}", encoding="utf-8")
            dump.write_text("{}", encoding="utf-8")
            typedb = TypeDB({})
            metadata = ({"app.TestEnum": {"Value": 1}}, {})
            converter = REUser3Converter(
                schema_path=schema,
                il2cpp_dump_path=dump,
            )

            with patch.object(TypeDB, "load", return_value=typedb) as load_schema:
                with patch.object(
                    User3Exporter,
                    "export_il2cpp_metadata_from_path",
                    return_value=metadata,
                ) as load_il2cpp:
                    first_exporter = converter._new_exporter(
                        root,
                        root / "out",
                        [],
                    )
                    second_exporter = converter._new_exporter(
                        root,
                        root / "out",
                        [],
                    )
                    packer = converter._new_packer(root / "packed")

                    self.assertIs(first_exporter.typedb, typedb)
                    self.assertIs(second_exporter.typedb, typedb)
                    self.assertIs(packer.typedb, typedb)
                    self.assertEqual(load_schema.call_count, 1)
                    self.assertEqual(load_il2cpp.call_count, 1)

                    schema.write_text('{"changed": true}', encoding="utf-8")
                    dump.write_text('{"changed": true}', encoding="utf-8")
                    converter._new_exporter(root, root / "out", [])
                    self.assertEqual(load_schema.call_count, 2)
                    self.assertEqual(load_il2cpp.call_count, 2)

                    converter.clear_metadata_cache()
                    converter._new_packer(root / "packed")
                    self.assertEqual(load_schema.call_count, 3)
                    self.assertEqual(load_il2cpp.call_count, 3)

    def test_patch_directory_reuses_one_exporter_and_packer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_root = root / "source"
            output_root = root / "output"
            source_root.mkdir()
            first = source_root / "first.user.3"
            second = source_root / "nested" / "second.user.3"
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            converter = REUser3Converter(
                schema_path=root / "schema.json",
                il2cpp_dump_path=root / "il2cpp_dump.json",
            )
            exporter = Mock()
            exporter._parse_user3_pack.side_effect = lambda path: {
                "name": Path(path).name
            }
            packer = Mock()
            packer.pack.side_effect = lambda data: data["name"].encode("utf-8")

            with patch.object(
                converter,
                "_new_exporter",
                return_value=exporter,
            ) as new_exporter:
                with patch.object(converter, "_prepare_exporter_metadata") as prepare:
                    with patch.object(
                        converter,
                        "_new_packer",
                        return_value=packer,
                    ) as new_packer:
                        result = converter.patch_directory(
                            source_root,
                            output_root,
                            lambda data, _path: data,
                        )

            self.assertEqual(
                result,
                {"total": 2, "success": 2, "failed": 0, "skipped": 0},
            )
            new_exporter.assert_called_once()
            prepare.assert_called_once_with(exporter)
            new_packer.assert_called_once_with(output_root)
            self.assertEqual(exporter._parse_user3_pack.call_count, 2)
            self.assertEqual(packer.pack.call_count, 2)
            self.assertEqual(
                (output_root / "first.user.3").read_bytes(),
                b"first.user.3",
            )
            self.assertEqual(
                (output_root / "nested" / "second.user.3").read_bytes(),
                b"second.user.3",
            )


if __name__ == "__main__":
    unittest.main()
