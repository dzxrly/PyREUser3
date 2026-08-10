"""Declarative USR container and embedded RSZ header layout registries.

Keep byte-layout evidence in this module and parsing/writing logic elsewhere.  The
outer USR container and the embedded RSZ header are independent dimensions: recent
RE Engine games share the modern header family while carrying different RSZ version
numbers and game-specific type schemas.

Primary references:

* https://github.com/praydog/REFramework/tree/master/reversing/rsz
* https://github.com/alphazolam/RE_RSZ/blob/main/RE_RSZ.bt
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


VERIFIED = "verified"
EXPERIMENTAL = "experimental"


@dataclass(frozen=True)
class AlignmentRule:
    """Describe how a section-relative offset is aligned in the physical file."""

    alignment: int
    origin: str

    def absolute_position(self, relative_offset: int, section_start: int) -> int:
        """Return the position whose alignment is constrained by this rule."""

        if self.origin == "file":
            return section_start + relative_offset
        if self.origin == "rsz":
            return relative_offset
        raise ValueError(f"unsupported alignment origin: {self.origin}")

    def is_aligned(self, relative_offset: int, section_start: int) -> bool:
        """Return whether an offset satisfies this rule."""

        if self.alignment <= 0:
            raise ValueError("alignment must be positive")
        return (
            self.absolute_position(relative_offset, section_start) % self.alignment == 0
        )


@dataclass(frozen=True)
class UsrLayoutCandidate:
    """Describe one independently detectable outer USR byte layout."""

    identifier: str
    status: str
    read_supported: bool
    repack_supported: bool
    evidence: tuple[str, ...]
    known_games: tuple[str, ...]
    header_struct: str
    header_fields: tuple[str, ...]
    header_size: int
    first_table_field: str
    require_first_table_at_header_end: bool
    table_alignment: int
    resource_entry_struct: str
    resource_entry_fields: tuple[str, ...]
    userdata_entry_struct: str
    userdata_entry_fields: tuple[str, ...]
    path_encoding: str
    table_offset_base: str
    resource_path_offset_base: str
    userdata_path_offset_base: str
    supports_resources: bool
    supports_usr_userdata: bool
    supports_usr_info: bool

    @property
    def semantic_header_size(self) -> int:
        return struct.calcsize(self.header_struct)

    @property
    def header_padding_size(self) -> int:
        return self.header_size - self.semantic_header_size

    @property
    def resource_entry_size(self) -> int:
        return struct.calcsize(self.resource_entry_struct)

    @property
    def userdata_entry_size(self) -> int:
        return struct.calcsize(self.userdata_entry_struct)


@dataclass(frozen=True)
class RszHeaderLayout:
    """Describe one embedded RSZ header and table family."""

    identifier: str
    status: str
    read_supported: bool
    repack_supported: bool
    evidence: tuple[str, ...]
    known_games: tuple[str, ...]
    version_min: int
    version_max: int | None
    header_struct: str
    header_fields: tuple[str, ...]
    instance_entry_struct: str
    instance_entry_fields: tuple[str, ...]
    rsz_userdata_alignment: int
    rsz_userdata_alignment_base: str
    rsz_userdata_entry_struct: str
    rsz_userdata_entry_fields: tuple[str, ...]
    rsz_userdata_path_offset_base: str
    rsz_data_alignment: int
    rsz_data_alignment_base: str
    supports_rsz_userdata: bool

    def supports_version(self, version: int) -> bool:
        if version < self.version_min:
            return False
        return self.version_max is None or version <= self.version_max

    @property
    def header_size(self) -> int:
        return struct.calcsize(self.header_struct)

    @property
    def instance_entry_size(self) -> int:
        return struct.calcsize(self.instance_entry_struct)

    @property
    def rsz_userdata_entry_size(self) -> int:
        return struct.calcsize(self.rsz_userdata_entry_struct)

    @property
    def userdata_alignment_rule(self) -> AlignmentRule:
        """Return the RSZ userdata table alignment rule."""

        return AlignmentRule(
            self.rsz_userdata_alignment,
            self.rsz_userdata_alignment_base,
        )

    @property
    def data_alignment_rule(self) -> AlignmentRule:
        """Return the RSZ instance-data alignment rule."""

        return AlignmentRule(
            self.rsz_data_alignment,
            self.rsz_data_alignment_base,
        )


_COMMON_USR_FIELDS = (
    "signature",
    "resource_count",
    "userdata_count",
    "info_count",
    "resource_info_tbl",
    "userdata_info_tbl",
    "data_offset",
)

_RECENT_RE_GAMES = (
    "Resident Evil 2/3/7 RT",
    "Resident Evil Village",
    "Monster Hunter Rise",
    "Street Fighter 6",
    "Resident Evil 4",
    "Dragon's Dogma 2",
    "Kunitsu-Gami",
    "Dead Rising Deluxe Remaster",
    "Monster Hunter Wilds",
    "Monster Hunter Stories 3: Twisted Reflection",
)


# Public tooling models the first 0x28 bytes as the semantic USR structure.  Modern
# writers align the first table to 0x30; some tools model bytes 0x28..0x2f as a
# reserved uint64 and others as alignment.  Preserve those bytes opaquely so both
# descriptions round-trip identically.
USR_H30_ABSOLUTE_UTF16Z = UsrLayoutCandidate(
    identifier="usr_h30_abs_utf16z",
    status=VERIFIED,
    read_supported=True,
    repack_supported=True,
    evidence=(
        "RE_RSZ USR core header is 0x28 bytes",
        "RszTool aligns the first USR table to 0x30",
        "REasy models the trailing 8 bytes as reserved",
        "verified against Monster Hunter Wilds .user.3 samples",
    ),
    known_games=_RECENT_RE_GAMES,
    header_struct="<IiiiQQQ",
    header_fields=_COMMON_USR_FIELDS,
    header_size=0x30,
    first_table_field="resource_info_tbl",
    require_first_table_at_header_end=True,
    table_alignment=0x10,
    resource_entry_struct="<II",
    resource_entry_fields=("path_offset", "reserved"),
    userdata_entry_struct="<IIQ",
    userdata_entry_fields=("class_hash", "crc", "path_offset"),
    path_encoding="utf-16-le-z",
    table_offset_base="file",
    resource_path_offset_base="file",
    userdata_path_offset_base="file",
    supports_resources=True,
    supports_usr_userdata=True,
    supports_usr_info=False,
)


# RE_RSZ exposes a 0x28 logical USR header, but no verified fixture currently proves
# that a real file places its first table at 0x28.  Keep this candidate readable for
# evidence collection while explicitly forbidding repack until a real round-trip
# fixture is available.  Requiring resourceInfoTbl == 0x28 prevents it from also
# matching ordinary H30 files.
USR_H28_ABSOLUTE_UTF16Z_EXPERIMENTAL = UsrLayoutCandidate(
    identifier="usr_h28_abs_utf16z_experimental",
    status=EXPERIMENTAL,
    read_supported=True,
    repack_supported=False,
    evidence=(
        "RE_RSZ declares a 0x28-byte logical USR header",
        "physical H28 table placement is not yet verified by a fixture",
    ),
    known_games=(),
    header_struct="<IiiiQQQ",
    header_fields=_COMMON_USR_FIELDS,
    header_size=0x28,
    first_table_field="resource_info_tbl",
    require_first_table_at_header_end=True,
    table_alignment=0x08,
    resource_entry_struct="<II",
    resource_entry_fields=("path_offset", "reserved"),
    userdata_entry_struct="<IIQ",
    userdata_entry_fields=("class_hash", "crc", "path_offset"),
    path_encoding="utf-16-le-z",
    table_offset_base="file",
    resource_path_offset_base="file",
    userdata_path_offset_base="file",
    supports_resources=True,
    supports_usr_userdata=True,
    supports_usr_info=False,
)


# Modern RSZ headers contain userdataCount/reserved/userdataOffset.  The numeric
# version is read from each file and preserved; version 16 is not special here.
RSZ_V4_PLUS = RszHeaderLayout(
    identifier="rsz_v4_plus",
    status=VERIFIED,
    read_supported=True,
    repack_supported=True,
    evidence=(
        "RE_RSZ uses the userdata-bearing RSZ header for modern games",
        "REasy selects this 0x30-byte header for version >= 4",
        "REasy aligns standard RSZ userdata and instance data in the full file",
        "verified against 62,768 Monster Hunter Wilds RSZ version 16 files",
        "verified against 42,945 Monster Hunter Stories 3 RSZ version 16 files",
    ),
    known_games=_RECENT_RE_GAMES,
    version_min=4,
    version_max=None,
    header_struct="<IIiiiiqqq",
    header_fields=(
        "magic",
        "version",
        "object_count",
        "instance_count",
        "userdata_count",
        "reserved",
        "instance_offset",
        "data_offset",
        "userdata_offset",
    ),
    instance_entry_struct="<II",
    instance_entry_fields=("type_hash", "crc"),
    rsz_userdata_alignment=0x10,
    rsz_userdata_alignment_base="file",
    rsz_userdata_entry_struct="<iIQ",
    rsz_userdata_entry_fields=("instance_id", "type_hash", "path_offset"),
    rsz_userdata_path_offset_base="rsz",
    rsz_data_alignment=0x10,
    rsz_data_alignment_base="file",
    supports_rsz_userdata=True,
)


# Original non-RT RE7 uses the short RSZ header and 16-byte instance entries.  It is
# useful for reading older files, but remains read-only until a licensed fixture is
# available for byte-for-byte repack validation.
RSZ_V3_LEGACY = RszHeaderLayout(
    identifier="rsz_v3_legacy",
    status=EXPERIMENTAL,
    read_supported=True,
    repack_supported=False,
    evidence=(
        "RE_RSZ omits userdata fields for original non-RT RE7",
        "REasy identifies the short header as RSZ version 3",
    ),
    known_games=("Resident Evil 7 (original non-RT)",),
    version_min=3,
    version_max=3,
    header_struct="<IIIIQQ",
    header_fields=(
        "magic",
        "version",
        "object_count",
        "instance_count",
        "instance_offset",
        "data_offset",
    ),
    instance_entry_struct="<IIQ",
    instance_entry_fields=("type_hash", "crc", "reserved"),
    rsz_userdata_alignment=8,
    rsz_userdata_alignment_base="rsz",
    rsz_userdata_entry_struct="<iIQ",
    rsz_userdata_entry_fields=("instance_id", "type_hash", "path_offset"),
    rsz_userdata_path_offset_base="rsz",
    rsz_data_alignment=0x10,
    rsz_data_alignment_base="file",
    supports_rsz_userdata=False,
)


USR_LAYOUTS = (USR_H30_ABSOLUTE_UTF16Z, USR_H28_ABSOLUTE_UTF16Z_EXPERIMENTAL)
RSZ_HEADER_LAYOUTS = (RSZ_V4_PLUS, RSZ_V3_LEGACY)

USR_LAYOUTS_BY_ID = {layout.identifier: layout for layout in USR_LAYOUTS}
RSZ_HEADER_LAYOUTS_BY_ID = {
    layout.identifier: layout for layout in RSZ_HEADER_LAYOUTS
}

# Compatibility with repack v3 files emitted by PyREUser3 0.7.0 before the outer
# and embedded layouts were separated.
USR_LAYOUT_ALIASES = {
    "usr3_h30_abs_utf16z_rsz16": USR_H30_ABSOLUTE_UTF16Z.identifier,
}

DEFAULT_USR_LAYOUT_ID = USR_H30_ABSOLUTE_UTF16Z.identifier
DEFAULT_RSZ_HEADER_LAYOUT_ID = RSZ_V4_PLUS.identifier


def get_usr_layout(identifier: str) -> UsrLayoutCandidate | None:
    """Return a registered outer layout, accepting stable legacy aliases."""

    canonical = USR_LAYOUT_ALIASES.get(identifier, identifier)
    return USR_LAYOUTS_BY_ID.get(canonical)


def get_rsz_header_layout(identifier: str) -> RszHeaderLayout | None:
    """Return one registered embedded RSZ header family."""

    return RSZ_HEADER_LAYOUTS_BY_ID.get(identifier)


def rsz_header_layouts_for_version(version: int) -> tuple[RszHeaderLayout, ...]:
    """Return readable RSZ header families compatible with a numeric version."""

    return tuple(
        layout
        for layout in RSZ_HEADER_LAYOUTS
        if layout.read_supported and layout.supports_version(version)
    )
