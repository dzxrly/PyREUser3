"""Collect shared constants, exceptions, binary readers, and layout utilities.

The helpers are intentionally independent of the exporter and packer so both directions
use the same low-level behavior.
"""

from __future__ import annotations

import re
import struct
import uuid
from pathlib import Path
from typing import Any

# Default magic for the outer USR header; it is little-endian text "USR\0" as an
# integer.
USR_MAGIC = 5395285
# Default magic for embedded RSZ blocks; callers may override it for
# game-specific variants.
RSZ_MAGIC = 5919570
# Preserve instance numbering and reference identity; RSZ object links depend on these
# indexes remaining stable.
PACK_JSON_FORMAT = "re_user3_pack_v1"
# Decode strings and GUID-like values conservatively so invalid data does not corrupt
# subsequent parsing.
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
# Register enum values through the shared lookup tables so readable labels and numeric
# packing stay reversible.
ENUM_UNUSED_KEY = "value__"


class ParseError(RuntimeError):
    """Signal expected binary-format problems separately from programming errors.
    """

    pass


def align(value: int, alignment: int) -> int:
    """Round an offset up to the requested byte alignment.

    Args:
        value (int): Value to parse, normalize, compare, or serialize.
        alignment (int): Byte alignment boundary.

    Returns:
        int: Integer decoded from input data, metadata, or the command-line option being parsed.
    """
    if alignment <= 1:
        return value
    # Round up by adding alignment - 1, then clear the low bits with an alignment mask.
    return (value + (alignment - 1)) & ~(alignment - 1)


def format_guid_text_from_hex32(hex32: str) -> str:
    """Format compact hexadecimal GUID text with canonical separators.

    Args:
        hex32 (str): Compact 32-character hexadecimal GUID text.

    Returns:
        str: Normalized or formatted text.
    """
    h = hex32.lower()
    # Insert separators using the canonical 8-4-4-4-12 GUID grouping.
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def normalize_guid_candidate_text(text: str) -> str:
    """Normalize a string when it appears to contain GUID text.

    Args:
        text (str): Text to normalize or parse.

    Returns:
        str: Normalized or formatted text.
    """
    # Strip whitespace, braces, and dashes before validating the compact 32-character hex form.
    stripped = text.strip().strip("{}")
    compact = stripped.replace("-", "")
    if HEX32_RE.fullmatch(compact):
        return format_guid_text_from_hex32(compact)
    return text


def resolve_schema_path(schema_path_or_dir: str | Path) -> Path:
    """Validate and return an explicit RE_RSZ schema JSON path.

    Args:
        schema_path_or_dir (str | Path): Schema argument accepted from older and newer call
        sites.

    Returns:
        Path: Concrete filesystem path returned after the read, write, or resolution step finishes.

    Raises:
        FileNotFoundError: A required file or directory was missing.
    """
    path = Path(schema_path_or_dir)
    if path.is_file():
        return path
    if path.is_dir():
        raise FileNotFoundError(
            f"schema must be an explicit RE RSZ json file, not a directory: {path}"
        )
    raise FileNotFoundError(f"schema file not found: {path}")


class BinaryReader:
    """Read little-endian values from a bounded byte buffer while protecting cursor movement.
    """

    def __init__(self, data: bytes):
        """Initialize BinaryReader with validated configuration and state.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Args:
            data (bytes): JSON tree or binary payload consumed by this conversion step.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.data = data
        # Cursor positions are absolute offsets from the start of the buffer so
        # nested readers can still report original file locations.
        self.pos = 0

    @property
    def size(self) -> int:
        """Return the total size of the reader buffer.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """

        return len(self.data)

    def tell(self) -> int:
        """Return the current absolute cursor offset.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """

        return self.pos

    def seek(self, pos: int) -> None:
        """Move the cursor to an absolute byte offset.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Args:
            pos (int): Absolute cursor position.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            ParseError: Binary data did not match the expected .user.3 or RSZ layout.
        """
        if pos < 0 or pos > self.size:
            raise ParseError(f"seek out of range: {pos}")
        self.pos = pos

    def read(self, n: int) -> bytes:
        """Read a fixed number of bytes from the current cursor.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Args:
            n (int): Number of bytes to read or advance.

        Returns:
            bytes: Encoded binary data ready to write to disk.

        Raises:
            ParseError: Binary data did not match the expected .user.3 or RSZ layout.
        """
        end = self.pos + n
        if end > self.size:
            raise ParseError(f"read out of range: {self.pos}+{n}")
        out = self.data[self.pos : end]
        self.pos = end
        return out

    def read_struct(self, fmt: str) -> Any:
        """Read struct.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Args:
            fmt (str): struct format string for one binary value.

        Returns:
            Any: Normalized value ready for the next parse, export, post-processing, or pack step.
        """
        size = struct.calcsize(fmt)
        raw = self.read(size)
        return struct.unpack(fmt, raw)[0]

    def read_u8(self) -> int:
        """Read u8.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<B")

    def read_s8(self) -> int:
        """Read s8.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<b")

    def read_u16(self) -> int:
        """Read u16.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<H")

    def read_s16(self) -> int:
        """Read s16.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<h")

    def read_u32(self) -> int:
        """Read u32.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<I")

    def read_s32(self) -> int:
        """Read s32.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<i")

    def read_u64(self) -> int:
        """Read u64.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<Q")

    def read_s64(self) -> int:
        """Read s64.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return self.read_struct("<q")

    def read_f32(self) -> float:
        """Read f32.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            float: Decoded floating-point number.
        """
        return self.read_struct("<f")

    def read_f64(self) -> float:
        """Read f64.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Returns:
            float: Decoded floating-point number.
        """
        return self.read_struct("<d")

    def read_wstring_null(self, offset: int) -> str:
        """Read wstring null.

        The method validates cursor bounds before reading so malformed data cannot move parsing
        past the buffer.

        Args:
            offset (int): Binary offset being read or written.

        Returns:
            str: Normalized or formatted text.
        """
        if offset < 0 or offset >= self.size:
            return ""
        out: list[int] = []
        i = offset
        # Resolve and validate paths at the boundary so later code never guesses
        # relative to a surprising working directory.
        while i + 1 < self.size:
            ch = struct.unpack_from("<H", self.data, i)[0]
            i += 2
            if ch == 0:
                break
            out.append(ch)
        return normalize_guid_candidate_text("".join(chr(c) for c in out))


def read_len_utf16(reader: BinaryReader) -> str:
    """Read a length-prefixed UTF-16LE string from the binary cursor.

    Args:
        reader (BinaryReader): BinaryReader positioned at the value to parse.

    Returns:
        str: Normalized or formatted text.
    """
    # Follow schema field layout exactly so alignment, padding, and unknown data remain
    # binary-compatible.
    reader.seek(align(reader.tell(), 4))
    length = reader.read_u32()
    if length == 0:
        return ""
    remaining_chars = (reader.size - reader.tell()) // 2
    # Decode strings and GUID-like values conservatively so invalid data does not
    # corrupt subsequent parsing.
    if length > remaining_chars or length > 2_000_000:
        return ""
    raw = reader.read(length * 2)
    decoded = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return normalize_guid_candidate_text(decoded)


def read_len_c8(reader: BinaryReader) -> str:
    """Read a length-prefixed UTF-8 C8 string from the binary cursor.

    Args:
        reader (BinaryReader): BinaryReader positioned at the value to parse.

    Returns:
        str: Normalized or formatted text.
    """
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
    """Read sixteen bytes and format them as GUID-like text.

    Args:
        reader (BinaryReader): BinaryReader positioned at the value to parse.

    Returns:
        str: Normalized or formatted text.
    """
    raw = reader.read(16)
    try:
        # Decode strings and GUID-like values conservatively so invalid data does not
        # corrupt subsequent parsing.
        return str(uuid.UUID(bytes_le=raw))
    except Exception:
        return format_guid_text_from_hex32(raw.hex())
