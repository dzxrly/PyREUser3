"""Open native tkinter file or directory dialogs for Web UI path selection.

Imports are delayed until a picker is requested so headless help output and server
startup do not initialize GUI resources.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# Serialize native picker usage and clean up GUI resources so repeated browser clicks do
# not leave stray windows.
_PICKER_LOCK = threading.Lock()


def pick_path(payload: dict[str, Any]) -> dict[str, str]:
    """Open a native picker and return the selected file or directory path.

    Args:
        payload (dict[str, Any]): JSON request body or Web form payload.

    Returns:
        dict[str, str]: Small JSON response mapping returned to the browser.

    Raises:
        ValueError: The caller supplied a missing, malformed, or out-of-range value.
    """
    # Serialize native picker usage and clean up GUI resources so repeated browser
    # clicks do not leave stray windows.
    # Delay the import so lightweight commands do not load heavy dependencies.
    import tkinter as tk
    from tkinter import filedialog

    kind = str(payload.get("kind", "file")).strip().lower()
    title = str(payload.get("title", "Select a path")).strip() or "Select a path"
    filetypes = _normalize_filetypes(payload.get("filetypes"))

    with _PICKER_LOCK:
        # Serialize native dialogs so multiple browser requests cannot open competing Tk windows.
        root = tk.Tk()
        root.withdraw()
        try:
            # Keep the local HTTP and frontend behavior explicit because the Web UI runs
            # without a separate framework.
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
            # Always destroy the temporary Tk root to release GUI resources after the dialog closes.
            root.destroy()

    # Follow schema field layout exactly so alignment, padding, and unknown data remain
    # binary-compatible.
    return {"path": str(Path(selected)) if selected else ""}


def _normalize_filetypes(raw: Any) -> list[tuple[str, str]]:
    """Normalize filetypes.

    Args:
        raw (Any): Raw metadata, JSON, or binary value being normalized.

    Returns:
        list[tuple[str, str]]: Configured object or normalized value returned for the caller to use directly.
    """
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
