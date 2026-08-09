"""Detect and parse the outer USR container using registered layout candidates."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from .core import ParseError
from .usr_layouts import (
    RSZ_HEADER_LAYOUTS,
    USR_LAYOUTS,
    RszHeaderLayout,
    UsrLayoutCandidate,
)


@dataclass(frozen=True)
class UsrResourceInfo:
    path: str
    reserved: int


@dataclass(frozen=True)
class UsrUserdataInfo:
    class_hash: int
    crc: int
    path: str


@dataclass(frozen=True)
class DetectedUsrContainer:
    layout: UsrLayoutCandidate
    rsz_layout: RszHeaderLayout
    header: dict[str, int]
    header_padding: bytes
    resources: tuple[UsrResourceInfo, ...]
    userdata: tuple[UsrUserdataInfo, ...]
    rsz_header: dict[str, int]


def _unpack_named(
    data: bytes, offset: int, fmt: str, fields: tuple[str, ...]
) -> dict[str, int]:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError(f"structure {fmt} at 0x{offset:x} exceeds file bounds")
    values = struct.unpack_from(fmt, data, offset)
    if len(values) != len(fields):
        raise ValueError(f"structure {fmt} does not match declared fields")
    return {name: int(value) for name, value in zip(fields, values)}


def _read_utf16z(data: bytes, offset: int, limit: int) -> str:
    if offset < 0 or offset >= limit or limit > len(data):
        raise ValueError(f"UTF-16 path offset 0x{offset:x} is outside its section")
    if offset & 1:
        raise ValueError(f"UTF-16 path offset 0x{offset:x} is not 2-byte aligned")
    end = offset
    while end + 1 < limit:
        if data[end] == 0 and data[end + 1] == 0:
            try:
                return data[offset:end].decode("utf-16-le", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(f"invalid UTF-16 path at 0x{offset:x}") from exc
        end += 2
    raise ValueError(f"unterminated UTF-16 path at 0x{offset:x}")


def _checked_table_end(offset: int, count: int, stride: int, limit: int) -> int:
    if count < 0:
        raise ValueError(f"negative table count: {count}")
    if offset < 0 or offset > limit:
        raise ValueError(f"table offset 0x{offset:x} is outside the USR section")
    end = offset + count * stride
    if end < offset or end > limit:
        raise ValueError(
            f"table 0x{offset:x}+{count}*{stride} exceeds section 0x{limit:x}"
        )
    return end


def _try_layout(
    data: bytes,
    layout: UsrLayoutCandidate,
    rsz_layout: RszHeaderLayout,
    user_magic: int,
    rsz_magic: int,
) -> DetectedUsrContainer:
    if layout.header_padding_size < 0:
        raise ValueError("declared USR header is smaller than its semantic structure")
    if len(data) < layout.header_size:
        raise ValueError(f"file is smaller than 0x{layout.header_size:x}-byte header")
    if layout.table_offset_base != "file":
        raise ValueError(f"unsupported table offset base: {layout.table_offset_base}")
    if layout.path_encoding != "utf-16-le-z":
        raise ValueError(f"unsupported path encoding: {layout.path_encoding}")

    header = _unpack_named(data, 0, layout.header_struct, layout.header_fields)
    if header["signature"] != user_magic:
        raise ValueError(f"USR magic mismatch: 0x{header['signature']:08x}")
    for count_name in ("resource_count", "userdata_count", "info_count"):
        if header[count_name] < 0:
            raise ValueError(f"{count_name} is negative")
    if header["resource_count"] and not layout.supports_resources:
        raise ValueError("nonzero USR resource table is not defined by this candidate")
    if header["userdata_count"] and not layout.supports_usr_userdata:
        raise ValueError("nonzero USR userdata table is not defined by this candidate")
    if header["info_count"] and not layout.supports_usr_info:
        raise ValueError("nonzero USR info table is not defined by this candidate")
    if layout.require_first_table_at_header_end:
        first_table = header[layout.first_table_field]
        if first_table != layout.header_size:
            raise ValueError(
                f"{layout.first_table_field} is 0x{first_table:x}, expected "
                f"0x{layout.header_size:x}"
            )

    rsz_start = header["data_offset"]
    if rsz_start < layout.header_size or rsz_start + rsz_layout.header_size > len(data):
        raise ValueError(f"RSZ offset 0x{rsz_start:x} is outside the file")

    resource_end = _checked_table_end(
        header["resource_info_tbl"],
        header["resource_count"],
        layout.resource_entry_size,
        rsz_start,
    )
    userdata_end = _checked_table_end(
        header["userdata_info_tbl"],
        header["userdata_count"],
        layout.userdata_entry_size,
        rsz_start,
    )
    if header["resource_info_tbl"] < layout.header_size:
        raise ValueError("resource table starts inside the USR header")
    if header["userdata_info_tbl"] < layout.header_size:
        raise ValueError("userdata table starts inside the USR header")
    if header["resource_info_tbl"] % layout.table_alignment:
        raise ValueError("resource table does not meet the candidate alignment")
    if header["userdata_info_tbl"] % layout.table_alignment:
        raise ValueError("userdata table does not meet the candidate alignment")
    if header["resource_count"] and header["userdata_count"]:
        resource_range = (header["resource_info_tbl"], resource_end)
        userdata_range = (header["userdata_info_tbl"], userdata_end)
        if max(resource_range[0], userdata_range[0]) < min(
            resource_range[1], userdata_range[1]
        ):
            raise ValueError("USR resource and userdata tables overlap")
    strings_floor = max(layout.header_size, resource_end, userdata_end)

    resources: list[UsrResourceInfo] = []
    for index in range(header["resource_count"]):
        offset = header["resource_info_tbl"] + index * layout.resource_entry_size
        item = _unpack_named(
            data, offset, layout.resource_entry_struct, layout.resource_entry_fields
        )
        path_offset = item["path_offset"]
        if layout.resource_path_offset_base != "file":
            raise ValueError(
                f"unsupported resource path base: {layout.resource_path_offset_base}"
            )
        if path_offset < strings_floor:
            raise ValueError(f"resource {index} path overlaps a USR table")
        resources.append(
            UsrResourceInfo(
                path=_read_utf16z(data, path_offset, rsz_start),
                reserved=item["reserved"] & 0xFFFFFFFF,
            )
        )

    userdata: list[UsrUserdataInfo] = []
    for index in range(header["userdata_count"]):
        offset = header["userdata_info_tbl"] + index * layout.userdata_entry_size
        item = _unpack_named(
            data, offset, layout.userdata_entry_struct, layout.userdata_entry_fields
        )
        path_offset = item["path_offset"]
        if layout.userdata_path_offset_base != "file":
            raise ValueError(
                f"unsupported userdata path base: {layout.userdata_path_offset_base}"
            )
        if path_offset < strings_floor:
            raise ValueError(f"userdata {index} path overlaps a USR table")
        userdata.append(
            UsrUserdataInfo(
                class_hash=item["class_hash"] & 0xFFFFFFFF,
                crc=item["crc"] & 0xFFFFFFFF,
                path=_read_utf16z(data, path_offset, rsz_start),
            )
        )

    rsz_header = _unpack_named(
        data, rsz_start, rsz_layout.header_struct, rsz_layout.header_fields
    )
    if rsz_header["magic"] != rsz_magic:
        raise ValueError(f"RSZ magic mismatch: 0x{rsz_header['magic']:08x}")
    if not rsz_layout.supports_version(rsz_header["version"]):
        raise ValueError(
            f"RSZ version {rsz_header['version']} does not match "
            f"{rsz_layout.identifier}"
        )
    rsz_header.setdefault("userdata_count", 0)
    rsz_header.setdefault("reserved", 0)
    rsz_header.setdefault("userdata_offset", rsz_header["data_offset"])
    for count_name in ("object_count", "instance_count", "userdata_count"):
        if rsz_header[count_name] < 0:
            raise ValueError(f"RSZ {count_name} is negative")

    object_table_end = rsz_layout.header_size + rsz_header["object_count"] * 4
    instance_offset = rsz_header["instance_offset"]
    data_offset = rsz_header["data_offset"]
    userdata_offset = rsz_header["userdata_offset"]
    if instance_offset < object_table_end:
        raise ValueError("RSZ instance table overlaps the object table")
    instance_end = (
        instance_offset
        + rsz_header["instance_count"] * rsz_layout.instance_entry_size
    )
    if instance_end < instance_offset or instance_end > data_offset:
        raise ValueError("RSZ instance table exceeds the data boundary")
    if data_offset < rsz_layout.header_size or rsz_start + data_offset > len(data):
        raise ValueError("RSZ data offset is outside the file")
    if rsz_layout.rsz_data_alignment_base == "file":
        if (rsz_start + data_offset) % rsz_layout.rsz_data_alignment:
            raise ValueError("RSZ data is not aligned to the absolute file position")
    else:
        raise ValueError(
            f"unsupported RSZ data alignment base: "
            f"{rsz_layout.rsz_data_alignment_base}"
        )

    if rsz_header["userdata_count"]:
        if not rsz_layout.supports_rsz_userdata:
            raise ValueError("RSZ userdata is not supported by this candidate")
        rsz_userdata_end = userdata_offset + (
            rsz_header["userdata_count"] * rsz_layout.rsz_userdata_entry_size
        )
        if userdata_offset < instance_end or rsz_userdata_end > data_offset:
            raise ValueError("RSZ userdata table exceeds its section")
        if rsz_layout.rsz_userdata_alignment_base == "rsz":
            userdata_position = userdata_offset
        elif rsz_layout.rsz_userdata_alignment_base == "file":
            userdata_position = rsz_start + userdata_offset
        else:
            raise ValueError(
                "unsupported RSZ userdata alignment base: "
                f"{rsz_layout.rsz_userdata_alignment_base}"
            )
        if userdata_position % rsz_layout.rsz_userdata_alignment:
            raise ValueError("RSZ userdata table does not meet candidate alignment")
        for index in range(rsz_header["userdata_count"]):
            offset = (
                rsz_start
                + userdata_offset
                + index * rsz_layout.rsz_userdata_entry_size
            )
            item = _unpack_named(
                data,
                offset,
                rsz_layout.rsz_userdata_entry_struct,
                rsz_layout.rsz_userdata_entry_fields,
            )
            path_offset = item["path_offset"]
            instance_id = item["instance_id"]
            if instance_id <= 0 or instance_id >= rsz_header["instance_count"]:
                raise ValueError(
                    f"RSZ userdata {index} has invalid instance id {instance_id}"
                )
            instance_info_offset = (
                rsz_start
                + instance_offset
                + instance_id * rsz_layout.instance_entry_size
            )
            instance_type_hash = struct.unpack_from("<I", data, instance_info_offset)[0]
            if (item["type_hash"] & 0xFFFFFFFF) != instance_type_hash:
                raise ValueError(
                    f"RSZ userdata {index} type hash does not match instance info"
                )
            if rsz_layout.rsz_userdata_path_offset_base != "rsz":
                raise ValueError(
                    "unsupported RSZ userdata path offset base: "
                    f"{rsz_layout.rsz_userdata_path_offset_base}"
                )
            if path_offset < rsz_userdata_end or path_offset >= data_offset:
                raise ValueError(f"RSZ userdata {index} path is outside its string pool")
            _read_utf16z(data, rsz_start + path_offset, rsz_start + data_offset)
    elif userdata_offset != data_offset:
        raise ValueError("empty RSZ userdata offset does not match data offset")

    padding_start = layout.semantic_header_size
    header_padding = data[padding_start : layout.header_size]
    return DetectedUsrContainer(
        layout=layout,
        rsz_layout=rsz_layout,
        header=header,
        header_padding=header_padding,
        resources=tuple(resources),
        userdata=tuple(userdata),
        rsz_header=rsz_header,
    )


def detect_usr_layout(
    data: bytes, user_magic: int, rsz_magic: int
) -> DetectedUsrContainer:
    """Select exactly one candidate after complete structural validation."""

    matches: list[DetectedUsrContainer] = []
    failures: list[str] = []
    for layout in USR_LAYOUTS:
        if not layout.read_supported:
            continue
        for rsz_layout in RSZ_HEADER_LAYOUTS:
            if not rsz_layout.read_supported:
                continue
            candidate_id = f"{layout.identifier}+{rsz_layout.identifier}"
            try:
                matches.append(
                    _try_layout(
                        data,
                        layout,
                        rsz_layout,
                        user_magic,
                        rsz_magic,
                    )
                )
            except (KeyError, struct.error, ValueError) as exc:
                failures.append(f"{candidate_id}: {exc}")
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        identifiers = ", ".join(
            f"{match.layout.identifier}+{match.rsz_layout.identifier}"
            for match in matches
        )
        raise ParseError(f"ambiguous USR layout candidates: {identifiers}")
    detail = "; ".join(failures) if failures else "no candidates registered"
    raise ParseError(f"unsupported USR layout: {detail}")
