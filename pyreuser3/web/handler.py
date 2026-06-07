"""HTTP request handler for the local Web UI and JSON API."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

from .jobs import JobStore
from .page import INDEX_HTML
from .picker import pick_path
from .runners import ConversionRunners
from .settings import WebSettings


def make_handler(
    settings: WebSettings,
    jobs: JobStore,
    runners: ConversionRunners,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler class bound to the current server state."""

    class WebHandler(BaseHTTPRequestHandler):
        """Implementation for WebHandler."""

        def log_message(self, format: str, *args: Any) -> None:
            """Handle log message."""
            print(f"{self.address_string()} - {format % args}")

        def do_GET(self) -> None:
            """Handle do GET."""
            path = urlparse(self.path).path
            if path == "/":
                # Keep Web UI behavior explicit and predictable.
                self._send_html(INDEX_HTML)
                return
            if path == "/api/jobs":
                # Keep this implementation detail explicit.
                self._handle_jobs()
                return
            if path.startswith("/api/jobs/"):
                # Keep this implementation detail explicit.
                self._handle_job(path.rsplit("/", 1)[-1])
                return
            self._send_json(404, {"error": "request path not found"})

        def do_POST(self) -> None:
            """Handle do POST."""
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/pick-path":
                    # Keep this implementation detail explicit.
                    self._send_json(200, pick_path(payload))
                    return
                if path == "/api/export":
                    # Keep this implementation detail explicit.
                    job = jobs.start("export", payload, runners.run_export)
                    self._send_json(202, {"jobId": job.id})
                    return
                self._send_json(404, {"error": "request path not found"})
            except Exception as exc:
                # Record per-file failures without stopping the whole batch.
                self._send_json(400, {"error": f"{exc.__class__.__name__}: {exc}"})

        def _read_json(self) -> dict[str, Any]:
            """Internal helper for read json."""
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _handle_jobs(self) -> None:
            """Internal helper for handle jobs."""
            payload = {
                "jobs": [
                    jobs.serialize(job, include_logs=False) for job in jobs.list_jobs()
                ],
                "rootDir": str(settings.root_dir),
            }
            self._send_json(200, payload)

        def _handle_job(self, job_id: str) -> None:
            """Internal helper for handle job."""
            job = jobs.get(job_id)
            if job is None:
                self._send_json(404, {"error": "job not found"})
                return
            self._send_json(200, {"job": jobs.serialize(job, include_logs=True)})

        def _send_html(self, html: str) -> None:
            """Internal helper for send html."""
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            """Internal helper for send json."""
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return WebHandler
