"""Define small dataclasses and aliases used while planning binary output.

The plan separates object references, struct payloads, scalar values, and instance
metadata before the writer serializes them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from ..core import PACK_JSON_FORMAT, ParseError, align
from ..schema import ClassDef


class PackError(ParseError):
    """Signal that JSON input cannot be converted into a valid .user.3 binary without losing
    required information.
    """


@dataclass(frozen=True)
class InstanceRef:
    """Represent a prepared reference to another RSZ instance by numeric instance id.

    Attributes:
        index (int): Instance index in the exported or planned RSZ instance table.
    """

    index: int


@dataclass
class StructValue:
    """Hold a schema class definition and prepared field values for an inline struct payload.

    Attributes:
        class_def (ClassDef): Schema class definition for an instance or struct.
        fields (dict[str, Any]): Ordered or named field definitions associated with a class or instance.
        declared_size (int): Byte size declared by schema metadata or preserved raw instance data.
    """

    class_def: ClassDef
    fields: dict[str, Any]
    declared_size: int


@dataclass
class InstanceSpec:
    """Describe one planned RSZ instance after class hash and schema resolution.

    Attributes:
        class_hash (int): RE_RSZ type hash for a class.
        class_def (ClassDef): Schema class definition for an instance or struct.
        fields (dict[str, Any]): Ordered or named field definitions associated with a class or instance.
    """

    class_hash: int
    class_def: ClassDef
    fields: dict[str, Any] = field(default_factory=dict)


class BinaryWriter:
    """Small byte buffer helper that writes little-endian primitive values and alignment
    padding for the packer.
    """

    def __init__(self) -> None:
        """Initialize BinaryWriter with validated configuration and state.

        The method appends bytes in little-endian order and keeps padding decisions centralized
        for the packer.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.data = bytearray()

    def tell(self) -> int:
        """Return the current absolute cursor offset.

        The method appends bytes in little-endian order and keeps padding decisions centralized
        for the packer.

        Returns:
            int: Integer decoded from input data, metadata, or the command-line option being parsed.
        """
        return len(self.data)

    def write(self, raw: bytes) -> None:
        """Append raw bytes to the writer buffer.

        The method appends bytes in little-endian order and keeps padding decisions centralized
        for the packer.

        Args:
            raw (bytes): Raw metadata, JSON, or binary value being normalized.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.data.extend(raw)

    def write_struct(self, fmt: str, *values: Any) -> None:
        """Write struct.

        The method appends bytes in little-endian order and keeps padding decisions centralized
        for the packer.

        Args:
            fmt (str): struct format string for one binary value.
            values (Any): Sequence of values to append to a binary section or buffer.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.write(struct.pack(fmt, *values))

    def align(self, alignment: int) -> None:
        """Round an offset up to the requested byte alignment.

        The method appends bytes in little-endian order and keeps padding decisions centralized
        for the packer.

        Args:
            alignment (int): Byte alignment boundary.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        target = align(self.tell(), alignment)
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))

    def pad_to(self, target: int) -> None:
        """Pad the accumulated binary buffer up to the requested absolute offset.

        The method appends bytes in little-endian order and keeps padding decisions centralized
        for the packer.

        Args:
            target (int): Absolute buffer offset or filesystem target required by the caller.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.

        Raises:
            PackError: JSON input could not be represented safely as .user.3 binary data.
        """
        if target < self.tell():
            raise PackError(f"cannot pad backwards: {self.tell()} -> {target}")
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))
