"""Expose the stable public API while keeping expensive converter modules lazy.

The package-level __getattr__ hook avoids importing Rich and binary conversion code for
lightweight operations such as version checks and Web UI help output.
"""

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
    """Resolve a lazily exported package attribute on first access.

    Args:
        name (str): Symbolic schema, class, field, or enum name being stored or looked up.

    Returns:
        Any: Normalized value ready for the next parse, export, post-processing, or pack step.
    """
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # Cache the resolved object in globals so later attribute access bypasses __getattr__ and avoids another import.
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
