"""Type database loader for RE_RSZ schema JSON files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """Compute the 32-bit MurmurHash3 value used by RE_RSZ type names."""
    c1 = 0xCC9E2D51
    c2 = 0x1B873593
    h1 = seed & 0xFFFFFFFF
    length = len(data)
    # Keep this implementation detail explicit.
    rounded_end = length & ~0x3

    # Preserve the RE_RSZ hashing behavior.
    for i in range(0, rounded_end, 4):
        k1 = int.from_bytes(data[i : i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    # Keep this implementation detail explicit.
    k1 = 0
    tail = data[rounded_end:]
    if len(tail) == 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    # Keep this implementation detail explicit.
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


@dataclass
class FieldDef:
    """Schema field definition used while parsing and packing RSZ data."""

    name: str
    field_type: str
    original_type: str
    size: int
    align: int
    is_array: bool


@dataclass
class ClassDef:
    """Schema class definition with CRC and field layout metadata."""

    name: str
    crc: int
    fields: list[FieldDef]


class TypeDB:
    """In-memory index of RE_RSZ schema class definitions."""

    def __init__(self, classes: dict[int, ClassDef]):
        """Initialize the instance."""
        self.classes = classes
        # Keep the JSON shape stable for callers and editors.
        self.name_to_hash = {c.name: h for h, c in classes.items()}

    @classmethod
    def load(cls, json_path: Path) -> "TypeDB":
        """Load load."""
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        classes: dict[int, ClassDef] = {}
        for key, value in raw.items():
            try:
                # Preserve the RE_RSZ hashing behavior.
                class_hash = int(key, 16)
            except ValueError:
                # Preserve field layout details for binary compatibility.
                continue
            fields: list[FieldDef] = []
            for field in value.get("fields", []):
                # Preserve field layout details for binary compatibility.
                fields.append(
                    FieldDef(
                        name=field.get("name", ""),
                        field_type=field.get("type", "Data"),
                        original_type=field.get("original_type", ""),
                        size=int(field.get("size", 0)),
                        align=int(field.get("align", 1)),
                        is_array=bool(field.get("array", False)),
                    )
                )
            crc_raw = value.get("crc", "0")
            # Preserve string and GUID decoding behavior.
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""), crc=crc, fields=fields
            )
        return cls(classes)

    def get_class(self, class_hash: int) -> ClassDef | None:
        """Get class."""
        return self.classes.get(class_hash)

    def resolve_struct_hash(self, original_type: str) -> int | None:
        """Resolve struct hash."""
        if not original_type:
            return None
        known = self.name_to_hash.get(original_type)
        if known is not None:
            return known
        # Preserve field layout details for binary compatibility.
        # Preserve the RE_RSZ hashing behavior.
        maybe = murmur3_32(original_type.encode("utf-8"), seed=0xFFFFFFFF)
        if maybe in self.classes:
            return maybe
        return None
