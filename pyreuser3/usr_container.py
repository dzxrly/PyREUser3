"""Detect and parse the outer USR container using registered layout candidates."""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .core import ParseError, RSZ_MAGIC, USR_MAGIC
from .usr_layouts import (
    RSZ_HEADER_LAYOUTS,
    USR_LAYOUTS,
    RszHeaderLayout,
    UsrLayoutCandidate,
)


LayoutDetectionPolicy = Literal["safe_read", "verified_repack", "strict_probe"]
LAYOUT_DETECTION_POLICIES = frozenset(
    {"safe_read", "verified_repack", "strict_probe"}
)


@dataclass(frozen=True)
class LayoutValidationIssue:
    """Describe a non-fatal physical-layout deviation found while parsing."""

    code: str
    message: str
    field: str
    observed: int | str
    expected: int | str
    severity: str = "warning"
    blocks_repack: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible diagnostic object."""

        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "field": self.field,
            "observed": self.observed,
            "expected": self.expected,
            "blocks_repack": self.blocks_repack,
        }


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
    issues: tuple[LayoutValidationIssue, ...] = ()


def _normalize_policy(policy: str) -> LayoutDetectionPolicy:
    normalized = str(policy).strip().lower().replace("-", "_")
    if normalized not in LAYOUT_DETECTION_POLICIES:
        raise ValueError(
            "layout detection policy must be safe_read, verified_repack, or strict_probe"
        )
    return cast(LayoutDetectionPolicy, normalized)


def _report_advisory(
    issues: list[LayoutValidationIssue],
    policy: LayoutDetectionPolicy,
    *,
    code: str,
    message: str,
    field: str,
    observed: int | str,
    expected: int | str,
    blocks_repack: bool = True,
) -> None:
    """Raise in strict mode or preserve a structured warning in read modes."""

    if policy == "strict_probe":
        raise ValueError(message)
    issues.append(
        LayoutValidationIssue(
            code=code,
            message=message,
            field=field,
            observed=observed,
            expected=expected,
            blocks_repack=blocks_repack,
        )
    )


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
    policy: LayoutDetectionPolicy | str = "strict_probe",
) -> DetectedUsrContainer:
    policy = _normalize_policy(policy)
    issues: list[LayoutValidationIssue] = []
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
        _report_advisory(
            issues,
            policy,
            code="USR_RESOURCE_TABLE_ALIGNMENT",
            message="resource table does not meet the candidate alignment",
            field="resource_info_tbl",
            observed=header["resource_info_tbl"],
            expected=f"absolute multiple of {layout.table_alignment}",
        )
    if header["userdata_info_tbl"] % layout.table_alignment:
        _report_advisory(
            issues,
            policy,
            code="USR_USERDATA_TABLE_ALIGNMENT",
            message="userdata table does not meet the candidate alignment",
            field="userdata_info_tbl",
            observed=header["userdata_info_tbl"],
            expected=f"absolute multiple of {layout.table_alignment}",
        )
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
    data_alignment = rsz_layout.data_alignment_rule
    if not data_alignment.is_aligned(data_offset, rsz_start):
        data_position = data_alignment.absolute_position(data_offset, rsz_start)
        _report_advisory(
            issues,
            policy,
            code="RSZ_DATA_ALIGNMENT",
            message="RSZ data does not meet the candidate alignment",
            field="data_offset",
            observed=data_position,
            expected=(
                f"{data_alignment.origin}-relative multiple of "
                f"{data_alignment.alignment}"
            ),
        )

    if rsz_header["userdata_count"]:
        if not rsz_layout.supports_rsz_userdata:
            raise ValueError("RSZ userdata is not supported by this candidate")
        rsz_userdata_end = userdata_offset + (
            rsz_header["userdata_count"] * rsz_layout.rsz_userdata_entry_size
        )
        if userdata_offset < instance_end or rsz_userdata_end > data_offset:
            raise ValueError("RSZ userdata table exceeds its section")
        userdata_alignment = rsz_layout.userdata_alignment_rule
        if not userdata_alignment.is_aligned(userdata_offset, rsz_start):
            userdata_position = userdata_alignment.absolute_position(
                userdata_offset, rsz_start
            )
            _report_advisory(
                issues,
                policy,
                code="RSZ_USERDATA_ALIGNMENT",
                message="RSZ userdata table does not meet candidate alignment",
                field="userdata_offset",
                observed=userdata_position,
                expected=(
                    f"{userdata_alignment.origin}-relative multiple of "
                    f"{userdata_alignment.alignment}"
                ),
            )
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
        _report_advisory(
            issues,
            policy,
            code="RSZ_EMPTY_USERDATA_OFFSET",
            message="empty RSZ userdata offset does not match data offset",
            field="userdata_offset",
            observed=userdata_offset,
            expected=data_offset,
        )

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
        issues=tuple(issues),
    )


def detect_usr_layout(
    data: bytes,
    user_magic: int,
    rsz_magic: int,
    policy: LayoutDetectionPolicy | str = "strict_probe",
) -> DetectedUsrContainer:
    """Select exactly one candidate after staged structural validation."""

    policy = _normalize_policy(policy)
    matches: list[DetectedUsrContainer] = []
    failures: list[str] = []
    for layout in USR_LAYOUTS:
        if not layout.read_supported:
            continue
        try:
            header = _unpack_named(data, 0, layout.header_struct, layout.header_fields)
            if header["signature"] != user_magic:
                raise ValueError(
                    f"USR magic mismatch: 0x{header['signature']:08x}"
                )
            rsz_start = header["data_offset"]
            rsz_prefix = _unpack_named(
                data,
                rsz_start,
                "<II",
                ("magic", "version"),
            )
            if rsz_prefix["magic"] != rsz_magic:
                raise ValueError(
                    f"RSZ magic mismatch: 0x{rsz_prefix['magic']:08x}"
                )
        except (KeyError, struct.error, ValueError) as exc:
            failures.append(f"{layout.identifier}: {exc}")
            continue

        compatible_rsz_layouts = [
            candidate
            for candidate in RSZ_HEADER_LAYOUTS
            if candidate.read_supported
            and candidate.supports_version(rsz_prefix["version"])
        ]
        if not compatible_rsz_layouts:
            failures.append(
                f"{layout.identifier}: no RSZ header layout supports version "
                f"{rsz_prefix['version']}"
            )
            continue
        for rsz_layout in compatible_rsz_layouts:
            candidate_id = f"{layout.identifier}+{rsz_layout.identifier}"
            try:
                matches.append(
                    _try_layout(
                        data,
                        layout,
                        rsz_layout,
                        user_magic,
                        rsz_magic,
                        policy=policy,
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


def _probe_result(
    detected: DetectedUsrContainer,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Convert a detected container to a compact JSON-compatible report."""

    rsz_start = detected.header["data_offset"]
    userdata_offset = detected.rsz_header["userdata_offset"]
    data_offset = detected.rsz_header["data_offset"]
    result: dict[str, Any] = {
        "ok": True,
        "layout": {
            "usr": detected.layout.identifier,
            "usr_status": detected.layout.status,
            "rsz_header": detected.rsz_layout.identifier,
            "rsz_status": detected.rsz_layout.status,
            "rsz_version": detected.rsz_header["version"],
        },
        "counts": {
            "resources": detected.header["resource_count"],
            "usr_userdata": detected.header["userdata_count"],
            "objects": detected.rsz_header["object_count"],
            "instances": detected.rsz_header["instance_count"],
            "rsz_userdata": detected.rsz_header["userdata_count"],
        },
        "offsets": {
            "rsz_start": rsz_start,
            "rsz_userdata": rsz_start + userdata_offset,
            "rsz_data": rsz_start + data_offset,
        },
        "issues": [issue.to_dict() for issue in detected.issues],
    }
    if source is not None:
        result["file"] = source
    return result


def probe_usr_file(
    path: str | Path,
    *,
    user_magic: int = USR_MAGIC,
    rsz_magic: int = RSZ_MAGIC,
    policy: LayoutDetectionPolicy | str = "safe_read",
) -> dict[str, Any]:
    """Inspect one .user.3 container without requiring a schema or il2cpp dump."""

    source = Path(path)
    detected = detect_usr_layout(
        source.read_bytes(),
        user_magic,
        rsz_magic,
        policy=policy,
    )
    return _probe_result(detected, source=str(source))


def probe_usr_path(
    root: str | Path,
    *,
    user_magic: int = USR_MAGIC,
    rsz_magic: int = RSZ_MAGIC,
    policy: LayoutDetectionPolicy | str = "safe_read",
    include_successes: bool = False,
) -> dict[str, Any]:
    """Inspect one file or a directory tree and return aggregate diagnostics."""

    policy = _normalize_policy(policy)
    source_root = Path(root)
    if source_root.is_file():
        files = [source_root]
    elif source_root.is_dir():
        files = sorted(source_root.rglob("*.user.3"))
    else:
        raise FileNotFoundError(f"probe input not found: {source_root}")
    if not files:
        raise FileNotFoundError(f"no *.user.3 found under: {source_root}")

    layouts: Counter[str] = Counter()
    versions: Counter[str] = Counter()
    issue_codes: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    success = failed = warned = 0
    for path in files:
        label = (
            path.name
            if source_root.is_file()
            else path.relative_to(source_root).as_posix()
        )
        try:
            detected = detect_usr_layout(
                path.read_bytes(),
                user_magic,
                rsz_magic,
                policy=policy,
            )
            success += 1
            layout_key = (
                f"{detected.layout.identifier}+{detected.rsz_layout.identifier}"
            )
            layouts[layout_key] += 1
            versions[str(detected.rsz_header["version"])] += 1
            for issue in detected.issues:
                issue_codes[issue.code] += 1
            if detected.issues:
                warned += 1
            if include_successes or detected.issues:
                records.append(_probe_result(detected, source=label))
        except Exception as exc:
            failed += 1
            records.append(
                {
                    "ok": False,
                    "file": label,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )

    return {
        "root": str(source_root),
        "policy": policy,
        "total": len(files),
        "success": success,
        "failed": failed,
        "warned": warned,
        "layouts": dict(sorted(layouts.items())),
        "rsz_versions": dict(sorted(versions.items())),
        "issue_codes": dict(sorted(issue_codes.items())),
        "files": records,
    }
