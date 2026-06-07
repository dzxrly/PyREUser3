"""Package marker for the local Web UI.

The Web UI is intentionally local-only and delegates conversion work to the same core
exporter used by the CLI.
"""

from .server import main, run_server
from .settings import WebSettings

__all__ = ["WebSettings", "main", "run_server"]
