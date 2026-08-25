"""Parse and validate pack-side USR/RSZ container metadata.

The repack document carries physical container information separately from the RSZ
instance graph.  This module turns that JSON boundary into one immutable plan before
instance planning or binary writing mutates packer state.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from .models import (
    ExternalUserdataSpec,
    InstanceSpec,
    PackError,
    RszUserdataSpec,
    StructValue,
    UsrResourceSpec,
    UsrUserdataSpec,
)
from ..core import PACK_JSON_FORMAT
from ..schema import ClassDef
from ..usr_layouts import (
    RszHeaderLayout,
    UsrLayoutCandidate,
    get_rsz_header_layout,
    get_usr_layout,
    rsz_header_layouts_for_version,
)


@dataclass(frozen=True)
class RepackContainer:
    """Validated physical metadata required to rebuild one ``.user.3`` container."""

    usr_layout: UsrLayoutCandidate
    rsz_layout: RszHeaderLayout
    usr_header_padding: bytes
    usr_resources: tuple[UsrResourceSpec, ...]
    usr_userdata: tuple[UsrUserdataSpec, ...]
    rsz_version: int
    rsz_reserved: int
    rsz_userdata: tuple[RszUserdataSpec, ...]


def parse_optional_u32(value: Any) -> int | None:
    """Parse an optional integer or hexadecimal string as unsigned 32-bit data."""

    if value is None:
        return None
    if isinstance(value, int):
        return value & 0xFFFFFFFF
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return int(text, 0) & 0xFFFFFFFF
    raise PackError(f"expected integer or hex string, got {value!r}")


def parse_required_u32(value: Any, label: str) -> int:
    """Parse a required unsigned 32-bit value with a document-path label."""

    parsed = parse_optional_u32(value)
    if parsed is None:
        raise PackError(f"{label} is required")
    return parsed


def parse_path(value: Any, label: str) -> str:
    """Validate a path-like JSON field without normalizing its binary spelling."""

    if not isinstance(value, str):
        raise PackError(f"{label} must be a string")
    if "\x00" in value:
        raise PackError(f"{label} cannot contain a NUL character")
    return value


def _parse_layout_metadata(
    data: dict[str, Any],
) -> tuple[str, UsrLayoutCandidate, RszHeaderLayout, int, int]:
    """Resolve and validate the outer and embedded layout declarations."""

    raw_layout = data.get("_layout")
    if not isinstance(raw_layout, dict):
        raise PackError("repack v3 must contain a _layout object")
    layout_id = raw_layout.get("usr")
    if not isinstance(layout_id, str) or not layout_id:
        raise PackError("repack v3 _layout.usr must be a layout id")
    usr_layout = get_usr_layout(layout_id)
    if usr_layout is None:
        raise PackError(f"unknown USR layout id: {layout_id}")
    if not usr_layout.repack_supported:
        raise PackError(f"USR layout {usr_layout.identifier} is read-only")

    rsz_version = raw_layout.get("rsz_version")
    if not isinstance(rsz_version, int):
        raise PackError("_layout.rsz_version must be an integer")
    rsz_layout = _resolve_rsz_layout(raw_layout.get("rsz_header"), rsz_version)
    if not rsz_layout.repack_supported:
        raise PackError(f"RSZ header layout {rsz_layout.identifier} is read-only")
    if not rsz_layout.supports_version(rsz_version):
        raise PackError(
            f"RSZ version {rsz_version} is not supported by header layout "
            f"{rsz_layout.identifier}"
        )

    rsz_reserved = raw_layout.get("rsz_reserved", 0)
    if not isinstance(rsz_reserved, int) or not -(1 << 31) <= rsz_reserved < (1 << 31):
        raise PackError("_layout.rsz_reserved must be a signed 32-bit integer")
    return layout_id, usr_layout, rsz_layout, rsz_version, rsz_reserved


def _resolve_rsz_layout(
    layout_id: Any, rsz_version: int
) -> RszHeaderLayout:
    """Resolve an explicit RSZ header id or one unambiguous version match."""

    if layout_id is None:
        inferred = rsz_header_layouts_for_version(rsz_version)
        if len(inferred) != 1:
            raise PackError(
                f"cannot infer one RSZ header layout for version {rsz_version}"
            )
        return inferred[0]
    if not isinstance(layout_id, str) or not layout_id:
        raise PackError("repack v3 _layout.rsz_header must be a layout id")
    layout = get_rsz_header_layout(layout_id)
    if layout is None:
        raise PackError(f"unknown RSZ header layout id: {layout_id}")
    return layout


def _parse_usr_metadata(
    data: dict[str, Any],
    layout_id: str,
    layout: UsrLayoutCandidate,
) -> tuple[bytes, tuple[UsrResourceSpec, ...], tuple[UsrUserdataSpec, ...]]:
    """Parse outer USR padding, dependency tables, and capability gates."""

    raw_usr = data.get("_usr")
    if not isinstance(raw_usr, dict):
        raise PackError("repack v3 must contain a _usr object")
    header_padding = _parse_header_padding(raw_usr, layout_id, layout)
    resources = _parse_usr_resources(raw_usr, layout_id, layout)
    userdata = _parse_usr_userdata(raw_usr, layout_id, layout)
    raw_info = raw_usr.get("info")
    if not isinstance(raw_info, list):
        raise PackError("_usr.info must be an array")
    if raw_info:
        raise PackError(
            f"layout {layout_id} cannot rebuild a nonempty USR info table"
        )
    return header_padding, resources, userdata


def _parse_header_padding(
    raw_usr: dict[str, Any],
    layout_id: str,
    layout: UsrLayoutCandidate,
) -> bytes:
    """Decode the opaque bytes between the semantic and physical USR headers."""

    padding_hex = raw_usr.get("header_padding_hex", "")
    if not isinstance(padding_hex, str):
        raise PackError("_usr.header_padding_hex must be hexadecimal text")
    try:
        header_padding = bytes.fromhex(padding_hex)
    except ValueError as exc:
        raise PackError("_usr.header_padding_hex is not valid hexadecimal") from exc
    if len(header_padding) != layout.header_padding_size:
        raise PackError(
            f"layout {layout_id} requires {layout.header_padding_size} header "
            f"padding bytes, got {len(header_padding)}"
        )
    return header_padding


def _parse_usr_resources(
    raw_usr: dict[str, Any],
    layout_id: str,
    layout: UsrLayoutCandidate,
) -> tuple[UsrResourceSpec, ...]:
    """Parse the outer resource dependency table."""

    raw_resources = raw_usr.get("resources")
    if not isinstance(raw_resources, list):
        raise PackError("_usr.resources must be an array")
    resources: list[UsrResourceSpec] = []
    for index, raw in enumerate(raw_resources):
        if not isinstance(raw, dict):
            raise PackError(f"_usr.resources[{index}] must be an object")
        resources.append(
            UsrResourceSpec(
                path=parse_path(raw.get("path"), f"_usr.resources[{index}].path"),
                reserved=parse_required_u32(
                    raw.get("reserved", 0),
                    f"_usr.resources[{index}].reserved",
                ),
            )
        )
    if resources and not layout.supports_resources:
        raise PackError(f"layout {layout_id} cannot rebuild USR resources")
    return tuple(resources)


def _parse_usr_userdata(
    raw_usr: dict[str, Any],
    layout_id: str,
    layout: UsrLayoutCandidate,
) -> tuple[UsrUserdataSpec, ...]:
    """Parse the outer userdata dependency table."""

    raw_userdata = raw_usr.get("userdata")
    if not isinstance(raw_userdata, list):
        raise PackError("_usr.userdata must be an array")
    userdata: list[UsrUserdataSpec] = []
    for index, raw in enumerate(raw_userdata):
        if not isinstance(raw, dict):
            raise PackError(f"_usr.userdata[{index}] must be an object")
        userdata.append(
            UsrUserdataSpec(
                class_hash=parse_required_u32(
                    raw.get("class_hash"),
                    f"_usr.userdata[{index}].class_hash",
                ),
                crc=parse_required_u32(
                    raw.get("crc", 0),
                    f"_usr.userdata[{index}].crc",
                ),
                path=parse_path(
                    raw.get("path"),
                    f"_usr.userdata[{index}].path",
                ),
            )
        )
    if userdata and not layout.supports_usr_userdata:
        raise PackError(f"layout {layout_id} cannot rebuild USR userdata")
    return tuple(userdata)


def _parse_rsz_userdata(
    data: dict[str, Any], layout: RszHeaderLayout
) -> tuple[RszUserdataSpec, ...]:
    """Parse the embedded RSZ userdata table and enforce unique instance ids."""

    raw_rsz = data.get("_rsz")
    if not isinstance(raw_rsz, dict):
        raise PackError("repack v3 must contain a _rsz object")
    raw_userdata = raw_rsz.get("userdata")
    if not isinstance(raw_userdata, list):
        raise PackError("_rsz.userdata must be an array")
    userdata: list[RszUserdataSpec] = []
    seen_instance_ids: set[int] = set()
    for index, raw in enumerate(raw_userdata):
        if not isinstance(raw, dict):
            raise PackError(f"_rsz.userdata[{index}] must be an object")
        instance_id = raw.get("instance_id")
        if not isinstance(instance_id, int) or instance_id <= 0:
            raise PackError(
                f"_rsz.userdata[{index}].instance_id must be a positive integer"
            )
        if instance_id in seen_instance_ids:
            raise PackError(f"duplicate RSZ userdata instance id: {instance_id}")
        seen_instance_ids.add(instance_id)
        userdata.append(
            RszUserdataSpec(
                instance_id=instance_id,
                type_hash=parse_required_u32(
                    raw.get("type_hash"),
                    f"_rsz.userdata[{index}].type_hash",
                ),
                path=parse_path(
                    raw.get("path"),
                    f"_rsz.userdata[{index}].path",
                ),
            )
        )
    if userdata and not layout.supports_rsz_userdata:
        raise PackError(
            f"RSZ header layout {layout.identifier} cannot rebuild userdata"
        )
    return tuple(userdata)


def parse_repack_container(data: dict[str, Any]) -> RepackContainer:
    """Build one validated container plan from a repack v3 JSON document."""

    format_name = data.get("_format")
    if format_name != PACK_JSON_FORMAT:
        raise PackError(
            f"{format_name} does not record USR/RSZ layout metadata; "
            "re-export the source file as repack v3 before packing"
        )
    (
        layout_id,
        usr_layout,
        rsz_layout,
        rsz_version,
        rsz_reserved,
    ) = _parse_layout_metadata(data)
    header_padding, resources, usr_userdata = _parse_usr_metadata(
        data, layout_id, usr_layout
    )
    rsz_userdata = _parse_rsz_userdata(data, rsz_layout)
    return RepackContainer(
        usr_layout=usr_layout,
        rsz_layout=rsz_layout,
        usr_header_padding=header_padding,
        usr_resources=resources,
        usr_userdata=usr_userdata,
        rsz_version=rsz_version,
        rsz_reserved=rsz_reserved,
        rsz_userdata=rsz_userdata,
    )


def validate_userdata_metadata(
    container: RepackContainer,
    instances: Sequence[InstanceSpec | ExternalUserdataSpec | None],
) -> None:
    """Ensure outer and embedded userdata tables agree with instance metadata."""

    external = {
        index: spec
        for index, spec in enumerate(instances)
        if isinstance(spec, ExternalUserdataSpec)
    }
    listed_ids = {item.instance_id for item in container.rsz_userdata}
    if listed_ids != set(external):
        raise PackError(
            "RSZ userdata table instance ids do not match userdata_reference "
            f"instances: table={sorted(listed_ids)}, instances={sorted(external)}"
        )
    for item in container.rsz_userdata:
        spec = external[item.instance_id]
        if item.type_hash != spec.class_hash or item.path != spec.path:
            raise PackError(
                f"RSZ userdata metadata does not match instance {item.instance_id}"
            )
    outer = [(item.class_hash, item.path) for item in container.usr_userdata]
    embedded = [(item.type_hash, item.path) for item in container.rsz_userdata]
    if outer != embedded:
        raise PackError("USR userdata dependencies do not match RSZ userdata order")


def validate_resource_metadata(
    container: RepackContainer,
    instances: Sequence[InstanceSpec | ExternalUserdataSpec | None],
) -> None:
    """Require every RSZ ``Resource`` value in the outer dependency table."""

    dependencies = {item.path for item in container.usr_resources}
    missing: set[str] = set()
    for spec in instances[1:]:
        if isinstance(spec, InstanceSpec):
            missing.update(
                path
                for path in _iter_struct_resources(spec.class_def, spec.fields)
                if path and path not in dependencies
            )
    if missing:
        raise PackError(
            "RSZ Resource values are missing from _usr.resources: "
            f"{sorted(missing)}"
        )


def _iter_struct_resources(
    class_def: ClassDef,
    fields: dict[str, Any],
) -> Iterator[str]:
    """Yield resource paths from one prepared instance or nested struct."""

    for field_def in class_def.fields:
        value = fields.get(field_def.name or "unnamed")
        values = value if field_def.is_array and isinstance(value, list) else [value]
        if field_def.field_type == "Resource":
            yield from (item for item in values if isinstance(item, str) and item)
            continue
        if field_def.field_type != "Struct":
            continue
        for item in values:
            if isinstance(item, StructValue):
                yield from _iter_struct_resources(item.class_def, item.fields)
