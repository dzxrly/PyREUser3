"""Parse the physical USR header and embedded RSZ sections of .user.3 files.

The parser returns intermediate documents that can be converted either to readable JSON
trees or to full pack-format JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core import BinaryReader, PACK_JSON_FORMAT, ParseError, align


class ExporterUser3ParserMixin:
    """Parse USR and RSZ sections of .user.3 files into intermediate documents and exportable
    trees.
    """

    def _parse_user3_document(self, user3_path: Path) -> dict[str, Any]:
        """Parse user3 document.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            user3_path (Path): Path to the .user.3 file being parsed, exported, patched, or packed.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.

        Raises:
            ParseError: Binary data did not match the expected .user.3 or RSZ layout.
        """
        reader = BinaryReader(user3_path.read_bytes())

        # The outer .user.3 container starts with a USR header; callers may override magic for game variants.
        magic = reader.read_u32()
        if magic != self.user_magic:
            raise ParseError(f"not a user file: magic={magic}")

        usr_header = {
            "signature": magic,
            "resource_count": reader.read_s32(),
            "userdata_count": reader.read_s32(),
            "info_count": reader.read_s32(),
            "resource_info_tbl": reader.read_u64(),
            "userdata_info_tbl": reader.read_u64(),
            "data_offset": reader.read_u64(),
        }
        header_userdata_infos: list[dict[str, Any]] = []
        if usr_header["userdata_count"] > 0 and usr_header["userdata_info_tbl"] > 0:
            try:
                # Resolve and validate paths at the boundary so later code never guesses
                # relative to a surprising working directory.
                reader.seek(usr_header["userdata_info_tbl"])
                for idx in range(usr_header["userdata_count"]):
                    class_hash = reader.read_u32()
                    crc = reader.read_u32()
                    path_offset = reader.read_u64()
                    class_def = self.typedb.get_class(class_hash, crc)
                    class_name = (
                        class_def.name
                        if class_def
                        else "Unknown Class"
                    )
                    header_userdata_infos.append(
                        {
                            "index": idx,
                            "class_hash": class_hash,
                            "class_name": class_name,
                            "path": reader.read_wstring_null(path_offset),
                        }
                    )
            except Exception:
                # Treat each file independently so one malformed resource is reported
                # but does not stop the rest of the batch.
                header_userdata_infos = []

        rsz_start = usr_header["data_offset"]

        # Apply RE Engine alignment and offset rules before touching binary fields;
        # later table offsets assume this layout.
        reader.seek(rsz_start)
        rsz_header = {
            "magic": reader.read_u32(),
            "version": reader.read_u32(),
            "object_count": reader.read_s32(),
            "instance_count": reader.read_s32(),
            "userdata_count": reader.read_s32(),
            "reserved": reader.read_s32(),
            "instance_offset": reader.read_s64(),
            "data_offset": reader.read_s64(),
            "userdata_offset": reader.read_s64(),
        }
        if rsz_header["magic"] != self.rsz_magic:
            raise ParseError(
                f"RSZ magic mismatch at data_offset: {rsz_header['magic']}"
            )

        # Preserve instance numbering and reference identity; RSZ object links depend on
        # these indexes remaining stable.
        reader.seek(rsz_start + 48)
        object_table = [
            reader.read_s32() for _i in range(max(rsz_header["object_count"], 0))
        ]
        object_table_set = set(object_table)

        instance_infos: list[dict[str, Any]] = []
        reader.seek(rsz_start + rsz_header["instance_offset"])
        for idx in range(max(rsz_header["instance_count"], 0)):
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            class_hash = reader.read_u32()
            crc = reader.read_u32()
            class_def = self.typedb.get_class(class_hash, crc)
            instance_infos.append(
                {
                    "index": idx,
                    "hash": class_hash,
                    "class_name": class_def.name if class_def else "Unknown Class",
                    "crc": crc,
                    "is_object": idx in object_table_set,
                }
            )
        instance_info_map = {item["index"]: item for item in instance_infos}

        rsz_userdata_instance_ids: list[int] = []
        rsz_userdata_path_by_instance: dict[int, str] = {}
        if rsz_header["userdata_count"] > 0 and rsz_header["userdata_offset"] > 0:
            try:
                # Preserve instance numbering and reference identity; RSZ object links
                # depend on these indexes remaining stable.
                reader.seek(rsz_start + rsz_header["userdata_offset"])
                for _i in range(rsz_header["userdata_count"]):
                    instance_id = reader.read_s32()
                    _type_hash = reader.read_u32()
                    path_offset = reader.read_u64()
                    if instance_id >= 0:
                        rsz_userdata_instance_ids.append(instance_id)
                        path = ""
                        if path_offset > 0 and rsz_start + path_offset < reader.size:
                            path = reader.read_wstring_null(rsz_start + path_offset)
                        rsz_userdata_path_by_instance[instance_id] = path
            except Exception:
                # Treat each file independently so one malformed resource is reported
                # but does not stop the rest of the batch.
                rsz_userdata_instance_ids = []
                rsz_userdata_path_by_instance = {}
        rsz_userdata_instance_set = set(rsz_userdata_instance_ids)

        parsed_instances: list[dict[str, Any]] = []
        reader.seek(rsz_start + rsz_header["data_offset"])
        for idx, info in enumerate(instance_infos):
            class_hash = int(info["hash"])
            if idx == 0:
                # Preserve instance numbering and reference identity; RSZ object links
                # depend on these indexes remaining stable.
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "note": "null instance slot",
                    }
                )
                continue
            if idx in rsz_userdata_instance_set:
                # Resolve and validate paths at the boundary so later code never guesses
                # relative to a surprising working directory.
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "is_userdata_reference": True,
                        "path": rsz_userdata_path_by_instance.get(idx, ""),
                    }
                )
                continue
            cls = self.typedb.get_class(class_hash, int(info["crc"]))
            if cls is None:
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "unparsed": True,
                        "reason": "class_not_found_in_schema",
                    }
                )
                continue
            if cls.fields:
                first = cls.fields[0]
                # Preserve instance numbering and reference identity; RSZ object links
                # depend on these indexes remaining stable.
                reader.seek(
                    align(reader.tell(), 4 if first.is_array else max(first.align, 1))
                )
            start_pos = reader.tell()
            try:
                parsed_instances.append(
                    {
                        "index": idx,
                        "data": self._parse_instance(
                            reader,
                            class_hash,
                            crc=int(info["crc"]),
                        ),
                    }
                )
            except Exception as exc:
                # Treat each file independently so one malformed resource is reported
                # but does not stop the rest of the batch.
                parsed_instances.append(
                    {
                        "index": idx,
                        "class_name": info["class_name"],
                        "unparsed": True,
                        "reason": str(exc),
                    }
                )
                min_skip = self._estimate_min_instance_size(cls)
                next_pos = min(reader.size, start_pos + min_skip)
                if next_pos <= start_pos:
                    break
                reader.seek(next_pos)

        idx_map = {
            inst["index"]: inst
            for inst in parsed_instances
            if isinstance(inst.get("index"), int)
        }
        object_roots = sorted(
            set(i for i in object_table if isinstance(i, int) and i >= 0)
        )
        if not object_roots:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            object_roots = self._infer_roots_when_object_table_empty(
                idx_map, parsed_instances
            )
        if not object_roots and rsz_userdata_instance_ids:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            object_roots = sorted(
                set(
                    i
                    for i in rsz_userdata_instance_ids
                    if i in instance_info_map and i > 0
                )
            )
        if not object_roots:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            object_roots = sorted(i for i in instance_info_map.keys() if i > 0)

        return {
            "user3_path": user3_path,
            "usr_header": usr_header,
            "rsz_header": rsz_header,
            "object_roots": object_roots,
            "instance_infos": instance_infos,
            "instance_info_map": instance_info_map,
            "parsed_instances": parsed_instances,
            "idx_map": idx_map,
            "header_userdata_infos": header_userdata_infos,
            "rsz_userdata_instance_ids": rsz_userdata_instance_ids,
            "rsz_userdata_path_by_instance": rsz_userdata_path_by_instance,
        }

    def _parse_user3(self, user3_path: Path) -> list[dict[str, Any]]:
        """Parse user3.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            user3_path (Path): Path to the .user.3 file being parsed, exported, patched, or packed.

        Returns:
            list[dict[str, Any]]: Raw userdata section dictionaries preserved for the pack document.
        """
        document = self._parse_user3_document(user3_path)
        parsed_instances = document["parsed_instances"]
        object_roots = document["object_roots"]
        instance_info_map = document["instance_info_map"]
        idx_map = document["idx_map"]
        header_userdata_infos = document["header_userdata_infos"]
        # Record raw sections that the minimal writer cannot rebuild so packing can reject lossy round trips.
        depth = (
            self._auto_pick_tree_depth(parsed_instances, object_roots)
            if self.tree_depth == "auto"
            else self.tree_depth
        )
        object_trees = [
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            self._build_compact_tree(
                root_idx,
                idx_map,
                depth=depth,
                instance_info_map=instance_info_map,
            )
            for root_idx in object_roots
            if root_idx in instance_info_map
        ]
        if not object_trees and header_userdata_infos:
            # Preserve instance numbering and reference identity; RSZ object links
            # depend on these indexes remaining stable.
            return [
                {
                    item["class_name"]: {
                        "ref_instance_id": item["index"],
                        "path": item["path"],
                    }
                }
                for item in header_userdata_infos
            ]
        return object_trees

    def _parse_user3_pack(self, user3_path: Path) -> dict[str, Any]:
        """Parse user3 pack.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            user3_path (Path): Path to the .user.3 file being parsed, exported, patched, or packed.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.
        """
        return self._build_pack_json(self._parse_user3_document(user3_path))

    def _build_pack_json(self, document: dict[str, Any]) -> dict[str, Any]:
        """Build pack json.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            document (dict[str, Any]): Exported JSON document or pack document being inspected.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.
        """
        instances: dict[str, Any] = {}
        warnings: list[str] = []
        unsupported: list[str] = []
        idx_map = document["idx_map"]
        path_by_userdata = document["rsz_userdata_path_by_instance"]
        usr_header = document["usr_header"]
        rsz_header = document["rsz_header"]

        # Instance 0 is the null reference slot and is represented as None in the exported document.
        if int(usr_header.get("resource_count", 0)) > 0:
            unsupported.append("USR resource table")
        if int(usr_header.get("userdata_count", 0)) > 0:
            unsupported.append("USR userdata table")
        if int(usr_header.get("info_count", 0)) > 0:
            unsupported.append("USR info table")
        if int(rsz_header.get("userdata_count", 0)) > 0:
            unsupported.append("RSZ userdata table")

        for info in document["instance_infos"]:
            idx = int(info["index"])
            class_hash = int(info["hash"])
            crc = int(info["crc"])
            entry: dict[str, Any] = {
                "_class": info.get("class_name"),
                "_hash": self._format_hex_u32(class_hash),
                "_crc": self._format_hex_u32(crc),
            }
            inst = idx_map.get(idx)
            if idx == 0:
                # Preserve instance numbering and reference identity; RSZ object links
                # depend on these indexes remaining stable.
                entry["_class"] = None
                entry["_kind"] = "null"
            elif inst is None:
                entry["_unparsed"] = True
                entry["reason"] = "missing parsed instance"
                warnings.append(f"instance {idx} is missing from parsed data")
            elif inst.get("is_userdata_reference"):
                entry["_kind"] = "userdata_reference"
                entry["path"] = path_by_userdata.get(idx, inst.get("path", ""))
                warnings.append(
                    f"instance {idx} is an external userdata reference and "
                    "cannot be rebuilt by the current minimal writer"
                )
            elif inst.get("unparsed"):
                entry["_unparsed"] = True
                entry["reason"] = inst.get("reason", "unparsed")
                warnings.append(
                    f"instance {idx} ({entry.get('_class')}) is unparsed: "
                    f"{entry['reason']}"
                )
            else:
                data = inst.get("data", {})
                class_name = data.get("_class") or entry.get("_class")
                entry["_class"] = class_name
                fields = data.get("fields", {})
                if not isinstance(fields, dict):
                    fields = {}
                # Register enum values through the shared lookup tables so readable
                # labels and numeric packing stay reversible.
                entry["fields"] = self._postprocess_enum_nodes(
                    fields,
                    current_class=class_name if isinstance(class_name, str) else None,
                )
            instances[str(idx)] = entry

        return {
            "_format": PACK_JSON_FORMAT,
            "_version": 1,
            "_source": {
                "file": str(document["user3_path"]),
                "user_magic": self._format_hex_u32(self.user_magic),
                "rsz_magic": self._format_hex_u32(self.rsz_magic),
                "schema": str(self.schema_path),
                "resource_count": int(usr_header.get("resource_count", 0)),
                "userdata_count": int(usr_header.get("userdata_count", 0)),
                "info_count": int(usr_header.get("info_count", 0)),
                "rsz_userdata_count": int(rsz_header.get("userdata_count", 0)),
            },
            "_roots": document["object_roots"],
            "_instances": instances,
            "_userdata": [
                {
                    "instance_id": int(instance_id),
                    "path": path_by_userdata.get(instance_id, ""),
                }
                for instance_id in document["rsz_userdata_instance_ids"]
            ],
            "_unsupported": unsupported,
            "_warnings": warnings,
        }

    @staticmethod
    def _format_hex_u32(value: int) -> str:
        """Format hex u32.

        The method keeps parsing, metadata lookup, and JSON shaping explicit so incomplete
        templates can still produce inspectable output.

        Args:
            value (int): Value to parse, normalize, compare, or serialize.

        Returns:
            str: Normalized or formatted text.
        """
        return f"0x{value & 0xFFFFFFFF:08x}"
