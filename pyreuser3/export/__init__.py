"""Expose the public exporter type for the export subpackage.

Implementation details are split across mixins, but callers can import User3Exporter
from this package directly.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["User3Exporter"]

_EXPORT_MODULES = {
    "User3Exporter": ".base",
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
