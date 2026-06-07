"""Shared binary parsing and packing helpers for .user.3 files."""

from __future__ import annotations

import re
import struct
import uuid
from pathlib import Path
from typing import Any

# Keep this implementation detail explicit.
USR_MAGIC = 5395285
# Keep this implementation detail explicit.
RSZ_MAGIC = 5919570
# Keep instance references stable while parsing or packing data.
PACK_JSON_FORMAT = "re_user3_pack_v1"
# Preserve string and GUID decoding behavior.
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
# Keep enum metadata consistent while converting values.
ENUM_UNUSED_KEY = "value__"


class ParseError(RuntimeError):
    """Raised when binary data does not match the expected .user.3 layout."""

    pass


def align(value: int, alignment: int) -> int:
    """Align an integer offset to the requested boundary."""
    if alignment <= 1:
        return value
    # Keep this implementation detail explicit.
    return (value + (alignment - 1)) & ~(alignment - 1)


def format_guid_text_from_hex32(hex32: str) -> str:
    """Format a compact 32-character hex string as a GUID."""
    h = hex32.lower()
    # Keep this implementation detail explicit.
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def normalize_guid_candidate_text(text: str) -> str:
    """Normalize text when it looks like a GUID."""
    # Keep this implementation detail explicit.
    stripped = text.strip().strip("{}")
    compact = stripped.replace("-", "")
    if HEX32_RE.fullmatch(compact):
        return format_guid_text_from_hex32(compact)
    return text


def resolve_schema_path(schema_path_or_dir: str | Path) -> Path:
    """Validate and return an explicit schema JSON path."""
    path = Path(schema_path_or_dir)
    if path.is_file():
        return path
    if path.is_dir():
        raise FileNotFoundError(
            f"schema must be an explicit RE RSZ json file, not a directory: {path}"
        )
    raise FileNotFoundError(f"schema file not found: {path}")


class BinaryReader:
    """Bounds-checked little-endian reader for binary buffers."""

    def __init__(self, data: bytes):
        """Initialize the instance."""
        self.data = data
        # Keep this implementation detail explicit.
        self.pos = 0

    @property
    def size(self) -> int:
        """Handle size."""

        return len(self.data)

    def tell(self) -> int:
        """Handle tell."""

        return self.pos

    def seek(self, pos: int) -> None:
        """Handle seek."""
        if pos < 0 or pos > self.size:
            raise ParseError(f"seek out of range: {pos}")
        self.pos = pos

    def read(self, n: int) -> bytes:
        """Read read."""
        end = self.pos + n
        if end > self.size:
            raise ParseError(f"read out of range: {self.pos}+{n}")
        out = self.data[self.pos : end]
        self.pos = end
        return out

    def read_struct(self, fmt: str) -> Any:
        """Read struct."""
        size = struct.calcsize(fmt)
        raw = self.read(size)
        return struct.unpack(fmt, raw)[0]

    def read_u8(self) -> int:
        """Read u8."""
        return self.read_struct("<B")

    def read_s8(self) -> int:
        """Read s8."""
        return self.read_struct("<b")

    def read_u16(self) -> int:
        """Read u16."""
        return self.read_struct("<H")

    def read_s16(self) -> int:
        """Read s16."""
        return self.read_struct("<h")

    def read_u32(self) -> int:
        """Read u32."""
        return self.read_struct("<I")

    def read_s32(self) -> int:
        """Read s32."""
        return self.read_struct("<i")

    def read_u64(self) -> int:
        """Read u64."""
        return self.read_struct("<Q")

    def read_s64(self) -> int:
        """Read s64."""
        return self.read_struct("<q")

    def read_f32(self) -> float:
        """Read f32."""
        return self.read_struct("<f")

    def read_f64(self) -> float:
        """Read f64."""
        return self.read_struct("<d")

    def read_wstring_null(self, offset: int) -> str:
        """Read wstring null."""
        if offset < 0 or offset >= self.size:
            return ""
        out: list[int] = []
        i = offset
        # Keep path handling explicit to avoid ambiguous working directories.
        while i + 1 < self.size:
            ch = struct.unpack_from("<H", self.data, i)[0]
            i += 2
            if ch == 0:
                break
            out.append(ch)
        return normalize_guid_candidate_text("".join(chr(c) for c in out))


def read_len_utf16(reader: BinaryReader) -> str:
    """Read a length-prefixed UTF-16LE string."""
    # Preserve field layout details for binary compatibility.
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining_chars = (reader.size - reader.tell()) // 2
    # Preserve string and GUID decoding behavior.
    if length > remaining_chars or length > 2_000_000:
        return ""
    raw = reader.read(length * 2)
    decoded = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_len_c8(reader: BinaryReader) -> str:
    """Read a length-prefixed UTF-8 string."""
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining = reader.size - reader.tell()
    if length > remaining or length > 2_000_000:
        return ""
    raw = reader.read(length)
    decoded = raw.decode("utf-8", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_guid_like(reader: BinaryReader) -> str:
    """Read a 16-byte GUID-like value."""
    raw = reader.read(16)
    try:
        # Preserve string and GUID decoding behavior.
        return str(uuid.UUID(bytes_le=raw))
    except Exception:
        return format_guid_text_from_hex32(raw.hex())
