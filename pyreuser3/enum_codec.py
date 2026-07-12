"""Shared enum, flag, and ``ace.Bitset`` conversion helpers.

The exporter and packer deliberately share these operations so readable labels remain
lossless across signed/unsigned storage widths and generic container wrappers.
"""

from __future__ import annotations

import re
from typing import Any


ENUM_LABEL_RE = re.compile(r"^\[(-?\d+)\]\s*(.*)$")
_GENERIC_RE = re.compile(r"^[^<]+<(.+)>$")


def normalize_integer_for_storage(value: int, storage_type: str | None) -> int:
    """Normalize an integer according to an enum's declared storage width/sign."""
    storage = storage_type or "S32"
    widths = {
        "S8": (8, True),
        "U8": (8, False),
        "S16": (16, True),
        "U16": (16, False),
        "S32": (32, True),
        "U32": (32, False),
        "S64": (64, True),
        "U64": (64, False),
    }
    bits, signed = widths.get(storage, (32, True))
    mask = (1 << bits) - 1
    normalized = int(value) & mask
    if signed and normalized >= 1 << (bits - 1):
        normalized -= 1 << bits
    return normalized


def parse_enum_label(value: Any) -> int | None:
    """Return the authoritative numeric prefix from ``[N] Name`` labels."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    match = ENUM_LABEL_RE.match(value.strip())
    if match:
        return int(match.group(1))
    return None


def enum_member_for_value(
    enum_lookup: dict[str, dict[int, tuple[str, int]]],
    enum_type: str,
    value: int,
    enum_underlying_types: dict[str, str] | None = None,
) -> tuple[str, int] | None:
    """Resolve a value without inventing 32-bit aliases for wider enum types."""
    value_map = enum_lookup.get(enum_type)
    if not value_map:
        return None
    storage = (enum_underlying_types or {}).get(enum_type, "S32")
    target = normalize_integer_for_storage(value, storage)
    direct = value_map.get(value)
    if direct is not None and normalize_integer_for_storage(direct[1], storage) == target:
        return direct
    for member_name, raw_value in value_map.values():
        if normalize_integer_for_storage(raw_value, storage) == target:
            return member_name, raw_value
    return None


def generic_arguments(type_name: str) -> list[str]:
    """Parse the simple, fully-qualified generic type names emitted by il2cpp dumps."""
    if not isinstance(type_name, str):
        return []
    match = _GENERIC_RE.match(type_name)
    if not match:
        return []
    # These metadata names are not assembly-qualified and current RE generic arguments
    # are flat. Keeping this parser intentionally strict prevents ambiguous guesses.
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def bitset_enum_type(class_name: str) -> str | None:
    """Return the generic enum argument for one ``ace.Bitset`1`` class."""
    if not isinstance(class_name, str) or not class_name.startswith("ace.Bitset`1<"):
        return None
    args = generic_arguments(class_name)
    return args[0] if len(args) == 1 else None


def is_probable_flags_enum(
    enum_type: str,
    value_map: dict[int, tuple[str, int]],
    storage_type: str | None = None,
) -> bool:
    """Conservatively identify bit-mask enums from their name and member values."""
    upper = enum_type.upper()
    markers = ("BIT", "BITS", "FLAG", "FLAGS", "MASK", "ATTR")
    if not any(marker in upper for marker in markers):
        return False
    storage = storage_type or "S32"
    width = int(storage[1:])
    mask = (1 << width) - 1
    values = {
        normalize_integer_for_storage(raw, storage) & mask
        for _name, raw in value_map.values()
        if raw != 0
    }
    basis = {value for value in values if value and value & (value - 1) == 0}
    if len(basis) < 2:
        return False
    known_mask = 0
    for value in basis:
        known_mask |= value
    return all(value & ~known_mask == 0 for value in values)


def decode_flags(
    enum_lookup: dict[str, dict[int, tuple[str, int]]],
    enum_type: str,
    value: int,
    enum_underlying_types: dict[str, str] | None = None,
) -> list[str]:
    """Expand a scalar mask to stable labels, preserving unknown bits explicitly."""
    storage = (enum_underlying_types or {}).get(enum_type, "S32")
    normalized = normalize_integer_for_storage(value, storage)
    bits = normalized if normalized >= 0 else normalized & ((1 << int(storage[1:])) - 1)
    value_map = enum_lookup.get(enum_type, {})
    if bits == 0:
        zero = enum_member_for_value(enum_lookup, enum_type, 0, enum_underlying_types)
        return [f"[0] {zero[0]}"] if zero else []
    labels: list[str] = []
    remaining = bits
    width_mask = (1 << int(storage[1:])) - 1
    members: list[tuple[int, str, int]] = []
    for name, raw in value_map.values():
        normalized_raw = normalize_integer_for_storage(raw, storage)
        mask_value = normalized_raw & width_mask
        if mask_value and mask_value & (mask_value - 1) == 0:
            members.append((mask_value, name, raw))
    for mask_value, name, raw in sorted(members):
        if remaining & mask_value:
            labels.append(f"[{raw}] {name}")
            remaining &= ~mask_value
    bit_index = 0
    while remaining:
        if remaining & 1:
            unknown_value = 1 << bit_index
            labels.append(f"[{unknown_value}] <unknown>")
        remaining >>= 1
        bit_index += 1
    return labels


def decode_bitset(
    words: list[int],
    enum_type: str,
    enum_lookup: dict[str, dict[int, tuple[str, int]]],
    max_element: int | None = None,
    enum_underlying_types: dict[str, str] | None = None,
) -> list[str]:
    """Decode 32-bit words into enum-index labels."""
    labels: list[str] = []
    for word_index, raw_word in enumerate(words):
        word = int(raw_word) & 0xFFFFFFFF
        for bit in range(32):
            index = word_index * 32 + bit
            if not (word & (1 << bit)):
                continue
            member = enum_member_for_value(
                enum_lookup, enum_type, index, enum_underlying_types
            )
            labels.append(f"[{index}] {member[0] if member else '<unknown>'}")
    return labels


def encode_bitset(
    labels: list[Any],
    enum_type: str,
    member_lookup: dict[str, dict[str, int]],
    max_element: int | None = None,
    word_count: int | None = None,
) -> list[int]:
    """Encode enum-index labels into 32-bit words, preserving requested padding."""
    indexes: list[int] = []
    members = member_lookup.get(enum_type, {})
    for item in labels:
        index = parse_enum_label(item)
        if index is None and isinstance(item, str):
            index = members.get(item.strip())
        if index is None or index < 0:
            raise ValueError(f"invalid {enum_type} bitset member: {item!r}")
        if (
            max_element is not None
            and index >= max_element
            and (word_count is None or index >= word_count * 32)
        ):
            raise ValueError(
                f"bitset index {index} exceeds _MaxElement {max_element} for {enum_type}"
            )
        indexes.append(index)
    selected_minimum = (max(indexes) + 32) // 32 if indexes else 0
    derived_count = max(
        selected_minimum,
        (max_element + 31) // 32 if max_element else 0,
    )
    count = derived_count if word_count is None else word_count
    if count < selected_minimum:
        raise ValueError(f"_WordCount {count} is too small for {enum_type} bitset")
    words = [0] * count
    for index in indexes:
        words[index // 32] |= 1 << (index % 32)
    return words


def encode_flags(
    values: list[Any], enum_type: str, member_lookup: dict[str, dict[str, int]]
) -> int:
    """Combine readable scalar flag labels back into one integer mask."""
    result = 0
    members = member_lookup.get(enum_type, {})
    for item in values:
        numeric = parse_enum_label(item)
        if numeric is None and isinstance(item, str):
            numeric = members.get(item.strip())
        if numeric is None:
            raise ValueError(f"invalid {enum_type} flag member: {item!r}")
        result |= numeric
    return result
