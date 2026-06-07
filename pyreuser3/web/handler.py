"""Serve the embedded single-page app and local JSON API endpoints.

The handler factory binds settings, job storage, and conversion runners into a
BaseHTTPRequestHandler subclass without storing global mutable state.
"""

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
    """Create a request handler class bound to current server dependencies.

    Args:
        settings (WebSettings): Resolved Web server settings.
        jobs (JobStore): Shared Web job store.
        runners (ConversionRunners): Conversion runner collection used by Web handlers.

    Returns:
        type[BaseHTTPRequestHandler]: Configured request-handler class bound to the supplied runners and job store.

    Raises:
        ValueError: The caller supplied a missing, malformed, or out-of-range value.
    """

    class WebHandler(BaseHTTPRequestHandler):
        """Handle the embedded Web page and local JSON API routes for job polling, path picking,
        and export submission.
        """

        def log_message(self, format: str, *args: Any) -> None:
            """Write a log entry for message.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Args:
                format (str): Logging format string supplied by BaseHTTPRequestHandler.
                args (Any): Parsed command-line namespace for the selected CLI command.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            print(f"{self.address_string()} - {format % args}")

        def do_GET(self) -> None:
            """Serve the Web page plus job-list and job-detail GET endpoints.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            path = urlparse(self.path).path
            if path == "/":
                # Keep the local HTTP and frontend behavior explicit because the Web UI
                # runs without a separate framework.
                self._send_html(INDEX_HTML)
                return
            if path == "/api/jobs":
                # The job list omits full logs so frequent polling responses stay small.
                self._handle_jobs()
                return
            if path.startswith("/api/jobs/"):
                # Job detail includes logs because the right-hand Web log panel displays the complete history.
                self._handle_job(path.rsplit("/", 1)[-1])
                return
            self._send_json(404, {"error": "request path not found"})

        def do_POST(self) -> None:
            """Route local Web API POST requests for path picking and export job submission.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            path = urlparse(self.path).path
            try:
                payload = self._read_json()
                if path == "/api/pick-path":
                    # Only open native file dialogs after an explicit browser button click.
                    self._send_json(200, pick_path(payload))
                    return
                if path == "/api/export":
                    # Submit the job immediately; a background worker performs
                    # conversion and records progress asynchronously.
                    job = jobs.start("export", payload, runners.run_export)
                    self._send_json(202, {"jobId": job.id})
                    return
                self._send_json(404, {"error": "request path not found"})
            except Exception as exc:
                # Treat each file independently so one malformed resource is reported
                # but does not stop the rest of the batch.
                self._send_json(400, {"error": f"{exc.__class__.__name__}: {exc}"})

        def _read_json(self) -> dict[str, Any]:
            """Read and validate a JSON request body.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Returns:
                dict[str, Any]: JSON-compatible dictionary for API or conversion callers.

            Raises:
                ValueError: The caller supplied a missing, malformed, or out-of-range value.
            """
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _handle_jobs(self) -> None:
            """Send a compact JSON snapshot of all tracked background jobs.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            payload = {
                "jobs": [
                    jobs.serialize(job, include_logs=False) for job in jobs.list_jobs()
                ],
                "rootDir": str(settings.root_dir),
            }
            self._send_json(200, payload)

        def _handle_job(self, job_id: str) -> None:
            """Send the detailed JSON snapshot for one background job.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Args:
                job_id (str): Identifier of the job to read or update.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            job = jobs.get(job_id)
            if job is None:
                self._send_json(404, {"error": "job not found"})
                return
            self._send_json(200, {"job": jobs.serialize(job, include_logs=True)})

        def _send_html(self, html: str) -> None:
            """Send the embedded Web page as an HTML response.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Args:
                html (str): HTML response body.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            """Send a JSON API response with the requested HTTP status.

            The method keeps local Web UI state and request handling explicit because there is no
            external framework managing these concerns.

            Args:
                status (int): HTTP status code or job status value.
                payload (dict[str, Any]): JSON request body or Web form payload.

            Returns:
                None. The method performs its documented side effect in place and raises on invalid input.
            """
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return WebHandler
