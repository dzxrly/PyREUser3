"""Native file and directory picker used by the local Web UI."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# Keep native picker handling predictable for local users.
_PICKER_LOCK = threading.Lock()


def pick_path(payload: dict[str, Any]) -> dict[str, str]:
    """Open a native picker and return the selected path."""
    # Keep native picker handling predictable for local users.
    # Delay the import so lightweight commands do not load heavy dependencies.
    import tkinter as tk
    from tkinter import filedialog

    kind = str(payload.get("kind", "file")).strip().lower()
    title = str(payload.get("title", "Select a path")).strip() or "Select a path"
    filetypes = _normalize_filetypes(payload.get("filetypes"))

    with _PICKER_LOCK:
        # Keep this implementation detail explicit.
        root = tk.Tk()
        root.withdraw()
        try:
            # Keep Web UI behavior explicit and predictable.
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            if kind == "directory":
                selected = filedialog.askdirectory(
                    parent=root,
                    title=title,
                    mustexist=False,
                )
            elif kind == "file":
                selected = filedialog.askopenfilename(
                    parent=root,
                    title=title,
                    filetypes=filetypes,
                )
            else:
                raise ValueError("path picker kind must be file or directory")
        finally:
            # Keep this implementation detail explicit.
            root.destroy()

    # Preserve field layout details for binary compatibility.
    return {"path": str(Path(selected)) if selected else ""}


def _normalize_filetypes(raw: Any) -> list[tuple[str, str]]:
    """Internal helper for normalize filetypes."""
    if not isinstance(raw, list):
        return [("All files", "*.*")]

    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        label = str(item[0]).strip()
        pattern = str(item[1]).strip()
        if label and pattern:
            out.append((label, pattern))
    return out or [("All files", "*.*")]
