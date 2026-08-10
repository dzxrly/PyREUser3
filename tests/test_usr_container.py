import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pyreuser3.core import PACK_JSON_FORMAT, ParseError, RSZ_MAGIC, USR_MAGIC
from pyreuser3.export.fields import ExporterFieldParserMixin
from pyreuser3.export.postprocess import ExporterPostprocessMixin
from pyreuser3.export.tree import ExporterTreeMixin
from pyreuser3.export.user3 import ExporterUser3ParserMixin
from pyreuser3.pack.models import PackError
from pyreuser3.pack.plan import PackerPlanMixin
from pyreuser3.pack.writer import PackerWriterMixin
from pyreuser3.schema import ClassDef, FieldDef, TypeDB
from pyreuser3.usr_container import (
    _try_layout,
    detect_usr_layout,
    probe_usr_file,
    probe_usr_path,
)
from pyreuser3.usr_layouts import (
    DEFAULT_RSZ_HEADER_LAYOUT_ID,
    DEFAULT_USR_LAYOUT_ID,
    RSZ_V3_LEGACY,
    RSZ_V4_PLUS,
    USR_H30_ABSOLUTE_UTF16Z,
    USR_H28_ABSOLUTE_UTF16Z_EXPERIMENTAL,
)


TEST_CLASS_HASH = 0x12345678
TEST_CLASS_CRC = 0x9ABCDEF0
TEST_CLASS_NAME = "app.TestResourceOwner"


class ContainerExporter(
    ExporterUser3ParserMixin,
    ExporterFieldParserMixin,
    ExporterPostprocessMixin,
    ExporterTreeMixin,
):
    def __init__(self, typedb: TypeDB, schema_path: Path):
        self.user_magic = USR_MAGIC
        self.rsz_magic = RSZ_MAGIC
        self.typedb = typedb
        self.schema_path = schema_path
        self.enum_lookup = {}
        self.class_field_fixed_types = {}
        self.serializable_to_fixed = {}
        self.generic_container_rules = {}
        self.generic_scalar_rules = {}
        self.bitset_rules = {}
        self.param_type_default_enum = {}
        self.enum_underlying_types = {}
        self.enum_flags = set()
        self.enum_member_to_types = {}


class ContainerPacker(PackerPlanMixin, PackerWriterMixin):
    def __init__(self, typedb: TypeDB):
        self.user_magic = USR_MAGIC
        self.rsz_magic = RSZ_MAGIC
        self.typedb = typedb
        self.enum_underlying_types = {}
        self.member_lookup = {}
        self.enum_lookup = {}
        self.enum_flags = set()
        self.bitset_rules = {}
        self.class_default_enums = {}
        self.instances = []

    @staticmethod
    def _to_s32(value: int) -> int:
        value &= 0xFFFFFFFF
        return value if value < 0x80000000 else value - 0x100000000

    def pack(self, data):
        return self._build_binary(self._plan_repack_input(data))


def make_repack_document(
    instances,
    roots,
    resources=None,
    usr_userdata=None,
    rsz_userdata=None,
    *,
    usr_layout_id=DEFAULT_USR_LAYOUT_ID,
    rsz_header_layout_id=DEFAULT_RSZ_HEADER_LAYOUT_ID,
    rsz_version=16,
    header_padding_hex="0102030405060708",
):
    layout = {
        "usr": usr_layout_id,
        "rsz_version": rsz_version,
        "rsz_reserved": 0,
    }
    if rsz_header_layout_id is not None:
        layout["rsz_header"] = rsz_header_layout_id
    return {
        "_format": PACK_JSON_FORMAT,
        "_version": 3,
        "_layout": layout,
        "_usr": {
            "header_padding_hex": header_padding_hex,
            "resources": resources or [],
            "userdata": usr_userdata or [],
            "info": [],
        },
        "_rsz": {"userdata": rsz_userdata or []},
        "_roots": roots,
        "_instances": instances,
        "_unsupported": [],
        "_warnings": [],
    }


class UsrContainerTests(unittest.TestCase):
    def setUp(self):
        class_def = ClassDef(
            name=TEST_CLASS_NAME,
            crc=TEST_CLASS_CRC,
            fields=[
                FieldDef(
                    name="dependency",
                    field_type="Resource",
                    original_type="via.render.TextureResourceHolder",
                    size=4,
                    align=4,
                    is_array=False,
                ),
                FieldDef(
                    name="label",
                    field_type="String",
                    original_type="System.String",
                    size=4,
                    align=4,
                    is_array=False,
                ),
            ],
        )
        self.typedb = TypeDB({TEST_CLASS_HASH: class_def})
        self.packer = ContainerPacker(self.typedb)

    def test_resource_layout_uses_absolute_rsz_data_alignment_and_round_trips(self):
        resource_path = "A/B/C.gpbf"
        document = make_repack_document(
            instances={
                "0": {"_class": None, "_kind": "null", "_hash": "0x00000000", "_crc": "0x00000000"},
                "1": {
                    "_class": TEST_CLASS_NAME,
                    "_hash": f"0x{TEST_CLASS_HASH:08x}",
                    "_crc": f"0x{TEST_CLASS_CRC:08x}",
                    "fields": {"dependency": resource_path, "label": ""},
                },
            },
            roots=[1],
            resources=[{"path": resource_path, "reserved": "0x10203040"}],
        )

        binary = self.packer.pack(document)
        detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)

        self.assertEqual(detected.layout.identifier, DEFAULT_USR_LAYOUT_ID)
        self.assertEqual(detected.header_padding, bytes.fromhex("0102030405060708"))
        self.assertEqual(detected.resources[0].path, resource_path)
        self.assertEqual(detected.resources[0].reserved, 0x10203040)
        absolute_data = detected.header["data_offset"] + detected.rsz_header["data_offset"]
        self.assertEqual(absolute_data % 16, 0)
        self.assertNotEqual(detected.rsz_header["data_offset"] % 16, 0)

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "fixture.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(self.typedb, Path(temp) / "schema.json")
            repack = exporter._parse_user3_pack(source)

        self.assertEqual(repack["_format"], PACK_JSON_FORMAT)
        self.assertEqual(repack["_unsupported"], [])
        self.assertEqual(self.packer.pack(repack), binary)

        edited_path = "A/Much/Longer/Resource/Dependency.gpbf"
        repack["_instances"]["1"]["fields"]["dependency"] = edited_path
        repack["_usr"]["resources"][0]["path"] = edited_path
        edited_binary = self.packer.pack(repack)
        edited = detect_usr_layout(edited_binary, USR_MAGIC, RSZ_MAGIC)
        self.assertEqual(edited.resources[0].path, edited_path)
        edited_absolute_data = edited.header["data_offset"] + edited.rsz_header["data_offset"]
        self.assertEqual(edited_absolute_data % 16, 0)

        repack["_instances"]["1"]["fields"]["dependency"] = "Missing.gpbf"
        with self.assertRaisesRegex(PackError, "missing from _usr.resources"):
            self.packer.pack(repack)

    def test_usr_and_rsz_userdata_tables_round_trip(self):
        type_hash = 0x0A32D148
        path = "GameDesign/Test/External.user"
        document = make_repack_document(
            instances={
                "0": {"_class": None, "_kind": "null", "_hash": "0x00000000", "_crc": "0x00000000"},
                "1": {
                    "_class": "Unknown Class",
                    "_kind": "userdata_reference",
                    "_hash": f"0x{type_hash:08x}",
                    "_crc": "0x00000000",
                    "path": path,
                },
            },
            roots=[1],
            usr_userdata=[
                {"class_hash": f"0x{type_hash:08x}", "crc": "0x00000000", "path": path}
            ],
            rsz_userdata=[
                {"instance_id": 1, "type_hash": f"0x{type_hash:08x}", "path": path}
            ],
        )

        binary = self.packer.pack(document)
        detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)
        self.assertEqual(detected.header["userdata_count"], 1)
        self.assertEqual(detected.rsz_header["userdata_count"], 1)
        self.assertEqual(detected.userdata[0].path, path)
        absolute_userdata = (
            detected.header["data_offset"]
            + detected.rsz_header["userdata_offset"]
        )
        self.assertEqual(absolute_userdata % 16, 0)

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "userdata.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(TypeDB({}), Path(temp) / "schema.json")
            repack = exporter._parse_user3_pack(source)

        self.assertEqual(repack["_unsupported"], [])
        self.assertEqual(self.packer.pack(repack), binary)

    def test_modern_userdata_uses_absolute_file_alignment_for_every_rsz_start_mod(self):
        observed_rsz_start_mods = set()
        for suffix_length in range(16):
            path = "GameDesign/Test/External" + ("x" * suffix_length) + ".user"
            document = make_repack_document(
                instances={
                    "0": {
                        "_class": None,
                        "_kind": "null",
                        "_hash": "0x00000000",
                        "_crc": "0x00000000",
                    },
                    "1": {
                        "_class": "Unknown Class",
                        "_kind": "userdata_reference",
                        "_hash": "0x0a32d148",
                        "_crc": "0x00000000",
                        "path": path,
                    },
                },
                roots=[1],
                usr_userdata=[
                    {
                        "class_hash": "0x0a32d148",
                        "crc": "0x00000000",
                        "path": path,
                    }
                ],
                rsz_userdata=[
                    {
                        "instance_id": 1,
                        "type_hash": "0x0a32d148",
                        "path": path,
                    }
                ],
            )

            binary = self.packer.pack(document)
            detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)
            rsz_start = detected.header["data_offset"]
            observed_rsz_start_mods.add(rsz_start % 16)
            absolute_userdata = rsz_start + detected.rsz_header["userdata_offset"]
            absolute_data = rsz_start + detected.rsz_header["data_offset"]
            self.assertEqual(absolute_userdata % 16, 0)
            self.assertEqual(absolute_data % 16, 0)

        self.assertEqual(observed_rsz_start_mods, set(range(0, 16, 2)))

    def test_safe_read_records_alignment_issue_while_strict_probe_rejects_it(self):
        path = "GameDesign/Test/External.user"
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                },
                "1": {
                    "_class": "Unknown Class",
                    "_kind": "userdata_reference",
                    "_hash": "0x0a32d148",
                    "_crc": "0x00000000",
                    "path": path,
                },
            },
            roots=[1],
            usr_userdata=[
                {
                    "class_hash": "0x0a32d148",
                    "crc": "0x00000000",
                    "path": path,
                }
            ],
            rsz_userdata=[
                {
                    "instance_id": 1,
                    "type_hash": "0x0a32d148",
                    "path": path,
                }
            ],
        )
        binary = self.packer.pack(document)
        relative_candidate = replace(
            RSZ_V4_PLUS,
            rsz_userdata_alignment=16,
            rsz_userdata_alignment_base="rsz",
        )

        detected = _try_layout(
            binary,
            USR_H30_ABSOLUTE_UTF16Z,
            relative_candidate,
            USR_MAGIC,
            RSZ_MAGIC,
            policy="safe_read",
        )
        self.assertEqual(
            [issue.code for issue in detected.issues],
            ["RSZ_USERDATA_ALIGNMENT"],
        )
        with self.assertRaisesRegex(ValueError, "userdata table"):
            _try_layout(
                binary,
                USR_H30_ABSOLUTE_UTF16Z,
                relative_candidate,
                USR_MAGIC,
                RSZ_MAGIC,
                policy="strict_probe",
            )

    def test_repack_export_blocks_a_layout_with_advisory_diagnostics(self):
        path = "GameDesign/Test/External.user"
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                },
                "1": {
                    "_class": "Unknown Class",
                    "_kind": "userdata_reference",
                    "_hash": "0x0a32d148",
                    "_crc": "0x00000000",
                    "path": path,
                },
            },
            roots=[1],
            usr_userdata=[
                {
                    "class_hash": "0x0a32d148",
                    "crc": "0x00000000",
                    "path": path,
                }
            ],
            rsz_userdata=[
                {
                    "instance_id": 1,
                    "type_hash": "0x0a32d148",
                    "path": path,
                }
            ],
        )
        binary = self.packer.pack(document)
        relative_candidate = replace(
            RSZ_V4_PLUS,
            rsz_userdata_alignment=16,
            rsz_userdata_alignment_base="rsz",
        )

        def detect_with_unverified_rule(raw_data, user_magic, rsz_magic, *, policy):
            return _try_layout(
                raw_data,
                USR_H30_ABSOLUTE_UTF16Z,
                relative_candidate,
                user_magic,
                rsz_magic,
                policy=policy,
            )

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "advisory.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(TypeDB({}), Path(temp) / "schema.json")
            exporter.json_format = "repack"
            with patch(
                "pyreuser3.export.user3.detect_usr_layout",
                side_effect=detect_with_unverified_rule,
            ):
                repack = exporter._parse_user3_pack(source)

        self.assertIn(
            "RSZ_USERDATA_ALIGNMENT",
            " ".join(repack["_warnings"]),
        )
        self.assertIn(
            "unverified layout diagnostics: RSZ_USERDATA_ALIGNMENT",
            repack["_unsupported"],
        )
        with self.assertRaisesRegex(PackError, "writer cannot rebuild"):
            self.packer.pack(repack)

    def test_safe_read_still_rejects_structural_userdata_corruption(self):
        path = "GameDesign/Test/External.user"
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                },
                "1": {
                    "_class": "Unknown Class",
                    "_kind": "userdata_reference",
                    "_hash": "0x0a32d148",
                    "_crc": "0x00000000",
                    "path": path,
                },
            },
            roots=[1],
            usr_userdata=[
                {
                    "class_hash": "0x0a32d148",
                    "crc": "0x00000000",
                    "path": path,
                }
            ],
            rsz_userdata=[
                {
                    "instance_id": 1,
                    "type_hash": "0x0a32d148",
                    "path": path,
                }
            ],
        )
        binary = self.packer.pack(document)
        detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)
        type_hash_offset = (
            detected.header["data_offset"]
            + detected.rsz_header["userdata_offset"]
            + 4
        )
        corrupted = bytearray(binary)
        original_hash = struct.unpack_from("<I", corrupted, type_hash_offset)[0]
        struct.pack_into("<I", corrupted, type_hash_offset, original_hash ^ 1)

        with self.assertRaisesRegex(
            ParseError,
            "type hash does not match instance info",
        ):
            detect_usr_layout(
                bytes(corrupted),
                USR_MAGIC,
                RSZ_MAGIC,
                policy="safe_read",
            )

    def test_probe_file_and_directory_do_not_require_schema(self):
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                }
            },
            roots=[],
        )
        binary = self.packer.pack(document)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "probe.user.3"
            source.write_bytes(binary)
            single = probe_usr_file(source)
            batch = probe_usr_path(temp, policy="strict_probe")

        self.assertTrue(single["ok"])
        self.assertEqual(single["layout"]["rsz_version"], 16)
        self.assertEqual(batch["total"], 1)
        self.assertEqual(batch["success"], 1)
        self.assertEqual(batch["failed"], 0)

    def test_modern_rsz_version_is_detected_and_preserved_instead_of_forced_to_16(self):
        for version in (4, 12, 16):
            with self.subTest(version=version):
                document = make_repack_document(
                    instances={
                        "0": {
                            "_class": None,
                            "_kind": "null",
                            "_hash": "0x00000000",
                            "_crc": "0x00000000",
                        },
                        "1": {
                            "_class": TEST_CLASS_NAME,
                            "_hash": f"0x{TEST_CLASS_HASH:08x}",
                            "_crc": f"0x{TEST_CLASS_CRC:08x}",
                            "fields": {"dependency": "", "label": ""},
                        },
                    },
                    roots=[1],
                    rsz_version=version,
                )
                binary = self.packer.pack(document)
                detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)
                self.assertEqual(detected.rsz_layout.identifier, RSZ_V4_PLUS.identifier)
                self.assertEqual(detected.rsz_header["version"], version)

                with tempfile.TemporaryDirectory() as temp:
                    source = Path(temp) / f"v{version}.user.3"
                    source.write_bytes(binary)
                    exporter = ContainerExporter(
                        self.typedb, Path(temp) / "schema.json"
                    )
                    repack = exporter._parse_user3_pack(source)

                self.assertEqual(
                    repack["_layout"]["rsz_header"], RSZ_V4_PLUS.identifier
                )
                self.assertEqual(repack["_layout"]["rsz_version"], version)
                self.assertEqual(self.packer.pack(repack), binary)

    def test_pre_split_v3_layout_id_and_missing_rsz_header_are_migrated(self):
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                }
            },
            roots=[],
            usr_layout_id="usr3_h30_abs_utf16z_rsz16",
            rsz_header_layout_id=None,
        )
        detected = detect_usr_layout(
            self.packer.pack(document), USR_MAGIC, RSZ_MAGIC
        )
        self.assertEqual(detected.layout.identifier, DEFAULT_USR_LAYOUT_ID)
        self.assertEqual(detected.rsz_layout.identifier, RSZ_V4_PLUS.identifier)

    def test_h28_candidate_is_detectable_but_repack_is_blocked(self):
        binary = struct.pack(
            "<IiiiQQQ", USR_MAGIC, 0, 0, 0, 0x28, 0x28, 0x28
        )
        binary += struct.pack(
            "<IIiiiiqqq", RSZ_MAGIC, 4, 0, 1, 0, 0, 0x30, 0x38, 0x38
        )
        binary += struct.pack("<II", 0, 0)

        detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)
        self.assertEqual(
            detected.layout.identifier,
            USR_H28_ABSOLUTE_UTF16Z_EXPERIMENTAL.identifier,
        )
        self.assertEqual(detected.header_padding, b"")

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "h28.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(TypeDB({}), Path(temp) / "schema.json")
            exported = exporter._parse_user3_pack(source)
        self.assertIn("read-only USR layout", " ".join(exported["_unsupported"]))
        self.assertIn("experimental USR layout", " ".join(exported["_warnings"]))

        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                }
            },
            roots=[],
            usr_layout_id=USR_H28_ABSOLUTE_UTF16Z_EXPERIMENTAL.identifier,
            header_padding_hex="",
            rsz_version=4,
        )
        with self.assertRaisesRegex(PackError, "USR layout .* is read-only"):
            self.packer.pack(document)

    def test_legacy_rsz_v3_is_detectable_but_repack_is_blocked(self):
        binary = struct.pack(
            "<IiiiQQQ", USR_MAGIC, 0, 0, 0, 0x30, 0x30, 0x30
        )
        binary += b"\x00" * 8
        binary += struct.pack("<IIIIQQ", RSZ_MAGIC, 3, 0, 1, 0x20, 0x30)
        binary += struct.pack("<IIQ", 0, 0, 0)

        detected = detect_usr_layout(binary, USR_MAGIC, RSZ_MAGIC)
        self.assertEqual(detected.layout.identifier, DEFAULT_USR_LAYOUT_ID)
        self.assertEqual(detected.rsz_layout.identifier, RSZ_V3_LEGACY.identifier)
        self.assertEqual(detected.rsz_header["userdata_count"], 0)

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "legacy.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(TypeDB({}), Path(temp) / "schema.json")
            exported = exporter._parse_user3_pack(source)
        self.assertIn(
            "read-only RSZ header layout", " ".join(exported["_unsupported"])
        )
        self.assertEqual(
            exported["_layout"]["rsz_header"], RSZ_V3_LEGACY.identifier
        )

        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                }
            },
            roots=[],
            rsz_header_layout_id=RSZ_V3_LEGACY.identifier,
            rsz_version=3,
        )
        with self.assertRaisesRegex(PackError, "RSZ header layout .* is read-only"):
            self.packer.pack(document)

    def test_readable_json_is_rejected_as_pack_input(self):
        with self.assertRaisesRegex(
            PackError, "packing requires repack JSON; readable JSON is read-only"
        ):
            self.packer.pack([{TEST_CLASS_NAME: {"dependency": "A/B/C.gpbf"}}])

    def test_negative_one_object_reference_null_sentinel_round_trips(self):
        class_hash = 0x2468ACE0
        class_crc = 0x13579BDF
        class_name = "app.NegativeNullReference"
        typedb = TypeDB(
            {
                class_hash: ClassDef(
                    name=class_name,
                    crc=class_crc,
                    fields=[
                        FieldDef(
                            name="target",
                            field_type="Object",
                            original_type="System.Object",
                            size=4,
                            align=4,
                            is_array=False,
                        )
                    ],
                )
            }
        )
        packer = ContainerPacker(typedb)
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                },
                "1": {
                    "_class": class_name,
                    "_hash": f"0x{class_hash:08x}",
                    "_crc": f"0x{class_crc:08x}",
                    "fields": {"target": {"ref_instance_id": -1}},
                },
            },
            roots=[1],
        )

        binary = packer.pack(document)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "negative-null.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(typedb, Path(temp) / "schema.json")
            exporter.json_format = "repack"
            repack = exporter._parse_user3_pack(source)

        self.assertEqual(
            repack["_instances"]["1"]["fields"]["target"],
            {"ref_instance_id": -1},
        )
        self.assertEqual(packer.pack(repack), binary)
        invalid = {**repack}
        invalid["_instances"] = {
            **repack["_instances"],
            "1": {
                **repack["_instances"]["1"],
                "fields": {"target": {"ref_instance_id": -2}},
            },
        }
        with self.assertRaisesRegex(PackError, "missing instance: -2"):
            packer.pack(invalid)

    def test_large_fixed_array_uses_lossless_raw_representation(self):
        class_hash = 0x10293847
        class_crc = 0x56473829
        class_name = "app.LargeFixedArray"
        typedb = TypeDB(
            {
                class_hash: ClassDef(
                    name=class_name,
                    crc=class_crc,
                    fields=[
                        FieldDef(
                            name="values",
                            field_type="U32",
                            original_type="System.UInt32",
                            size=4,
                            align=4,
                            is_array=True,
                        )
                    ],
                )
            }
        )
        packer = ContainerPacker(typedb)
        document = make_repack_document(
            instances={
                "0": {
                    "_class": None,
                    "_kind": "null",
                    "_hash": "0x00000000",
                    "_crc": "0x00000000",
                },
                "1": {
                    "_class": class_name,
                    "_hash": f"0x{class_hash:08x}",
                    "_crc": f"0x{class_crc:08x}",
                    "fields": {"values": [1, 2, 3, 4]},
                },
            },
            roots=[1],
        )
        binary = packer.pack(document)

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "large-array.user.3"
            source.write_bytes(binary)
            exporter = ContainerExporter(typedb, Path(temp) / "schema.json")
            exporter.json_format = "repack"
            with patch("pyreuser3.export.fields.LARGE_ARRAY_RAW_THRESHOLD", 2):
                repack = exporter._parse_user3_pack(source)

        raw_array = repack["_instances"]["1"]["fields"]["values"]
        self.assertEqual(raw_array["_raw_array_count"], 4)
        self.assertEqual(len(bytes.fromhex(raw_array["_raw_array_hex"])), 16)
        self.assertIn("large fixed-width array", " ".join(repack["_warnings"]))
        self.assertEqual(packer.pack(repack), binary)

        raw_array["_raw_array_count"] = 5
        with self.assertRaisesRegex(PackError, "16 bytes, expected 20"):
            packer.pack(repack)


if __name__ == "__main__":
    unittest.main()
