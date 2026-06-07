"""Rich progress bar and logging helpers for batch commands."""

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

# Keep Rich rendering and logging on the shared console.
_CONSOLE = Console()


def get_console() -> Console:
    """Return the shared Rich console."""
    return _CONSOLE


class BatchProgress:
    """Rich progress display that keeps logs above the progress bar."""

    def __init__(self, description: str, total: int, unit: str = "file") -> None:
        """Initialize the instance."""
        self.description = description
        self.total = total
        self.unit = unit
        self.console = get_console()
        # Keep Rich rendering and logging on the shared console.
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
        """Enter the context manager."""
        self._progress.__enter__()
        self._task_id = self._progress.add_task(self.description, total=self.total)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """Exit the context manager."""
        self._progress.__exit__(exc_type, exc, tb)
        return False

    def log(self, message: str, style: str | None = None) -> None:
        """Handle log."""
        self.console.log(message, style=style)

    def update(self, advance: int = 1, description: str | None = None) -> None:
        """Update update."""
        if self._task_id is None:
            return
        kwargs: dict[str, Any] = {"advance": advance}
        if description is not None:
            kwargs["description"] = description
        self._progress.update(self._task_id, **kwargs)
