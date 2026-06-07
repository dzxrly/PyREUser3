"""Runtime settings shared by the local Web UI server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebSettings:
    """Configuration shared by the Web server and task runners."""

    host: str = "127.0.0.1"
    port: int = 8765
    root_dir: Path = Path.cwd()
    max_jobs: int = 50

    def with_resolved_root(self) -> "WebSettings":
        """Handle with resolved root."""
        # Keep this implementation detail explicit.
        return WebSettings(
            host=self.host,
            port=self.port,
            root_dir=self.root_dir.expanduser().resolve(),
            max_jobs=self.max_jobs,
        )
