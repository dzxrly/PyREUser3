"""Server entry point for the local Vue Web UI."""

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
    """Threading HTTP server that allows recently used ports to be reused."""

    allow_reuse_address = True


def run_server(settings: WebSettings) -> None:
    """Start the local Web server and block until it stops."""
    # Keep path handling explicit to avoid ambiguous working directories.
    settings = settings.with_resolved_root()

    # Keep this implementation detail explicit.
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
        # Keep this implementation detail explicit.
        server.server_close()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse Web server command line arguments."""
    parser = argparse.ArgumentParser(description="Start the local Vue Web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to listen on.")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on.")
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
    """Run the command entry point."""
    args = parse_args(argv)
    run_server(
        WebSettings(
            host=args.host,
            port=args.port,
            root_dir=Path(args.root_dir),
            max_jobs=args.max_jobs,
        )
    )
