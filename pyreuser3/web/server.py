"""Parse Web UI command line options, assemble server dependencies, and run the local HTTP server.

The server resolves its compatibility root once at startup and keeps request routing,
job state, and conversion work separated.
"""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Sequence

from .handler import make_handler
from .jobs import JobStore
from .runners import ConversionRunners
from .settings import WebSettings


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server variant that can immediately reuse a recently released local port.
    """

    allow_reuse_address = True


def run_server(settings: WebSettings) -> None:
    """Start the configured local Web server and block until interrupted.

    Args:
        settings (WebSettings): Resolved Web server settings.

    Returns:
        None. The method performs its documented side effect in place and raises on invalid input.
    """
    # Resolve and validate paths at the boundary so later code never guesses relative to
    # a surprising working directory.
    settings = settings.with_resolved_root()

    # Resolve settings once before startup; form paths still come from explicit picker selections.
    jobs = JobStore(max_jobs=settings.max_jobs)
    runners = ConversionRunners(settings.root_dir)
    handler = make_handler(settings, jobs, runners)

    server = ReusableThreadingHTTPServer((settings.host, settings.port), handler)
    url = f"http://{settings.host}:{settings.port}/"
    print(f"RE User3 JSON Web is running at: {url}")
    print("Web form paths are not inferred from the project root; select them manually.")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        # Always close the server so the local port is released after shutdown.
        server.server_close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the Web server.

    Args:
        argv (Sequence[str] | None): Optional argument list; None means use the process command line.

    Returns:
        argparse.Namespace: Parsed command-line arguments for the Web server entry point.
    """
    parser = argparse.ArgumentParser(description="Start the local Vue Web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface where the local Web server listens.")
    parser.add_argument("--port", type=int, default=8765, help="TCP port where the local Web server listens.")
    parser.add_argument(
        "--root-dir",
        default=str(Path.cwd()),
        help="Compatibility setting; Web form paths must still be selected as absolute paths.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=50,
        help="Maximum number of jobs to keep in memory.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the command entry point.

    Args:
        argv (Sequence[str] | None): Optional argument list; None means use the process command line.

    Returns:
        None. The method performs its documented side effect in place and raises on invalid input.
    """
    args = parse_args(argv)
    run_server(
        WebSettings(
            host=args.host,
            port=args.port,
            root_dir=Path(args.root_dir),
            max_jobs=args.max_jobs,
        )
    )
