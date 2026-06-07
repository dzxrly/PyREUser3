"""Define immutable runtime settings for the local Web UI server.

A resolved copy is used at startup so path expansion happens once and later code can
treat settings as stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebSettings:
    """Keep immutable host, port, root directory, and job-retention settings for the Web
    server.

    Attributes:
        host (str): Host interface where the local Web server listens.
        port (int): TCP port where the local Web server listens.
        root_dir (Path): Compatibility root directory for Web settings.
        max_jobs (int): Maximum number of retained Web jobs.
    """

    host: str = "127.0.0.1"
    port: int = 8765
    root_dir: Path = Path.cwd()
    max_jobs: int = 50

    def with_resolved_root(self) -> "WebSettings":
        """Return settings with project root resolved to an absolute directory.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Returns:
            'WebSettings': New settings object with an absolute, validated project root.
        """
        # Return a new frozen dataclass instance instead of mutating settings in place.
        return WebSettings(
            host=self.host,
            port=self.port,
            root_dir=self.root_dir.expanduser().resolve(),
            max_jobs=self.max_jobs,
        )
