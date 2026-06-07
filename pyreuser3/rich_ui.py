"""Wrap Rich progress rendering so batch logs scroll above a persistent progress bar.

Exporter and packer commands share this module to keep terminal output consistent across
long-running file batches.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

# Route progress bars and log messages through the same Rich console so terminal
# rendering remains coherent.
_CONSOLE = Console()


def get_console() -> Console:
    """Return the shared Rich console used by progress bars and log output.


    Returns:
        Console: Shared Rich console when Rich is installed, otherwise the fallback console.
    """
    return _CONSOLE


class BatchProgress:
    """Manage one Rich progress task and log messages above it during batch operations.
    """

    def __init__(self, description: str, total: int, unit: str = "file") -> None:
        """Initialize BatchProgress with validated configuration and state.

        Args:
            description (str): Progress text shown in the terminal UI.
            total (int): Total number of items expected by the progress display.
            unit (str): Human-readable unit label for progress updates.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.description = description
        self.total = total
        self.unit = unit
        self.console = get_console()
        # Route progress bars and log messages through the same Rich console so terminal
        # rendering remains coherent.
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn(unit),
            TextColumn("elapsed"),
            TimeElapsedColumn(),
            TextColumn("eta"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
            transient=False,
        )
        self._task_id: TaskID | None = None

    def __enter__(self) -> "BatchProgress":
        """Start progress rendering and create the tracked task.


        Returns:
            'BatchProgress': Context manager instance that updates the progress display.
        """
        self._progress.__enter__()
        self._task_id = self._progress.add_task(self.description, total=self.total)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """Stop progress rendering and propagate any context exception.

        Args:
            exc_type (Any): Exception type passed by the context-manager protocol.
            exc (Any): Exception instance passed by the context-manager protocol.
            tb (Any): Traceback object passed by the context-manager protocol.

        Returns:
            bool: True when the inspected value matches the expected schema or metadata pattern; otherwise False.
        """
        self._progress.__exit__(exc_type, exc, tb)
        return False

    def log(self, message: str, style: str | None = None) -> None:
        """Write a human-readable log entry.

        Args:
            message (str): Human-readable status or log message.
            style (str | None): Optional Rich style name used when rendering terminal output.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self.console.log(message, style=style)

    def update(self, advance: int = 1, description: str | None = None) -> None:
        """Advance the Rich progress task and optionally update its label.

        Args:
            advance (int): Number of completed units to add to the progress counter.
            description (str | None): Progress text shown in the terminal UI.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        if self._task_id is None:
            return
        kwargs: dict[str, Any] = {"advance": advance}
        if description is not None:
            kwargs["description"] = description
        self._progress.update(self._task_id, **kwargs)
