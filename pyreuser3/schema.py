"""Load RE_RSZ schema JSON into dataclasses that the parser and writer can query by class hash or type name.

The module also implements the MurmurHash3 variant used by RE_RSZ type names when a
struct is referenced by name but not directly indexed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


def murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """Compute the MurmurHash3 variant used by RE_RSZ type names.

    Args:
        data (bytes): JSON tree or binary payload consumed by this conversion step.
        seed (int): Initial hash seed used by the MurmurHash3-compatible schema hash.

    Returns:
        int: Integer decoded from input data, metadata, or the command-line option being parsed.
    """
    c1 = 0xCC9E2D51
    c2 = 0x1B873593
    h1 = seed & 0xFFFFFFFF
    length = len(data)
    # rounded_end marks the final complete four-byte block, matching the MurmurHash3 block layout.
    rounded_end = length & ~0x3

    # Keep the MurmurHash3 implementation byte-for-byte compatible with RE_RSZ schema
    # type hashes.
    for i in range(0, rounded_end, 4):
        k1 = int.from_bytes(data[i : i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    # Mix the remaining one to three tail bytes in little-endian order before finalization.
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

    # Finalize by folding the length and high/low bits into the 32-bit hash result.
    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


@dataclass
class FieldDef:
    """Describe one schema field, including name, logical type, original type, size, alignment,
    and array status.

    Attributes:
        name (str): Symbolic schema, class, field, or enum name being stored or looked up.
        field_type (str): Normalized RE Engine field type used to choose binary read/write behavior.
        original_type (str): Original schema type text used to detect enum, class, and array semantics.
        size (int): Declared byte size of the field or serialized value.
        align (int): Required byte alignment for the value in the RSZ layout.
        is_array (bool): Whether the schema field represents a variable-length array.
    """

    name: str
    field_type: str
    original_type: str
    size: int
    align: int
    is_array: bool


@dataclass
class ClassDef:
    """Describe one schema class, including its name, CRC, and ordered field definitions.

    Attributes:
        name (str): Symbolic schema, class, field, or enum name being stored or looked up.
        crc (int): Schema CRC/hash value that identifies a class definition.
        fields (list[FieldDef]): Ordered or named field definitions associated with a class or instance.
    """

    name: str
    crc: int
    fields: list[FieldDef]


class TypeDB:
    """Index RE_RSZ class definitions by hash and by name for parser and packer lookups.
    """

    def __init__(self, classes: dict[int, ClassDef]):
        """Initialize TypeDB with validated configuration and state.

        Args:
            classes (dict[int, ClassDef]): Mapping from class CRC/hash values to parsed class definitions.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.classes = classes
        # Preserve the exported JSON structure so external scripts and hand-edited files
        # remain compatible across workflows.
        self.name_to_hash = {c.name: h for h, c in classes.items()}

    @classmethod
    def load(cls, json_path: Path) -> "TypeDB":
        """Load the schema JSON file into an indexed type database.

        Args:
            json_path (Path): Path to the JSON document read from or written by this workflow.

        Returns:
            'TypeDB': Configured object or normalized value returned for the caller to use directly.
        """
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        classes: dict[int, ClassDef] = {}
        for key, value in raw.items():
            try:
                # Keep the MurmurHash3 implementation byte-for-byte compatible with
                # RE_RSZ schema type hashes.
                class_hash = int(key, 16)
            except ValueError:
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
                continue
            fields: list[FieldDef] = []
            for field in value.get("fields", []):
                # Follow schema field layout exactly so alignment, padding, and unknown
                # data remain binary-compatible.
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
            # Decode strings and GUID-like values conservatively so invalid data does
            # not corrupt subsequent parsing.
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""), crc=crc, fields=fields
            )
        return cls(classes)

    def get_class(self, class_hash: int) -> ClassDef | None:
        """Get class.

        Args:
            class_hash (int): RE_RSZ type hash for a class.

        Returns:
            ClassDef | None: Matching class definition when the schema contains the requested identifier.
        """
        return self.classes.get(class_hash)

    def resolve_struct_hash(self, original_type: str) -> int | None:
        """Resolve struct hash.

        Args:
            original_type (str): Original schema type text used to detect enum, class, and array semantics.

        Returns:
            int | None: Resolved numeric value, or None when the source cannot be mapped.
        """
        if not original_type:
            return None
        known = self.name_to_hash.get(original_type)
        if known is not None:
            return known
        # Follow schema field layout exactly so alignment, padding, and unknown data
        # remain binary-compatible.
        # Keep the MurmurHash3 implementation byte-for-byte compatible with RE_RSZ
        # schema type hashes.
        maybe = murmur3_32(original_type.encode("utf-8"), seed=0xFFFFFFFF)
        if maybe in self.classes:
            return maybe
        return None
