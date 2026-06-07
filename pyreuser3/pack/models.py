"""Dataclasses used by the .user.3 packing plan."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from ..core import PACK_JSON_FORMAT, ParseError, align
from ..schema import ClassDef


class PackError(ParseError):
    """Implementation for PackError."""


@dataclass(frozen=True)
class InstanceRef:
    """Implementation for InstanceRef."""

    index: int


@dataclass
class StructValue:
    """Implementation for StructValue."""

    class_def: ClassDef
    fields: dict[str, Any]
    declared_size: int


@dataclass
class InstanceSpec:
    """Planned RSZ instance with type metadata and prepared field values."""

    class_hash: int
    class_def: ClassDef
    fields: dict[str, Any] = field(default_factory=dict)


class BinaryWriter:
    """Implementation for BinaryWriter."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self.data = bytearray()

    def tell(self) -> int:
        """Handle tell."""
        return len(self.data)

    def write(self, raw: bytes) -> None:
        """Write write."""
        self.data.extend(raw)

    def write_struct(self, fmt: str, *values: Any) -> None:
        """Write struct."""
        self.write(struct.pack(fmt, *values))

    def align(self, alignment: int) -> None:
        """Align an integer offset to the requested boundary."""
        target = align(self.tell(), alignment)
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))

    def pad_to(self, target: int) -> None:
        """Handle pad to."""
        if target < self.tell():
            raise PackError(f"cannot pad backwards: {self.tell()} -> {target}")
        if target > self.tell():
            self.write(b"\x00" * (target - self.tell()))
