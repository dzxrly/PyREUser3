"""Expose the public packer type for rebuilding .user.3 files from JSON.

Packing internals are split into planning and writer mixins for clarity.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["PackError", "User3Packer"]

_EXPORT_MODULES = {
    "PackError": ".models",
    "User3Packer": ".base",
}


def __getattr__(name: str) -> Any:
    """Resolve lazily exported subpackage attributes on first access."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
