"""Public package exports for the RE User3 JSON toolkit."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BinaryReader",
    "ClassDef",
    "FieldDef",
    "PackError",
    "ParseError",
    "TypeDB",
    "REUser3Converter",
    "RSZ_MAGIC",
    "User3Exporter",
    "User3Packer",
    "USR_MAGIC",
]

_EXPORT_MODULES = {
    "BinaryReader": ".core",
    "ParseError": ".core",
    "RSZ_MAGIC": ".core",
    "USR_MAGIC": ".core",
    "ClassDef": ".schema",
    "FieldDef": ".schema",
    "TypeDB": ".schema",
    "PackError": ".pack",
    "User3Packer": ".pack",
    "User3Exporter": ".export",
    "REUser3Converter": ".api",
}


def __getattr__(name: str) -> Any:
    """Lazily resolve public package exports."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Keep this implementation detail explicit.
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
