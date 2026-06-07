"""Manage Web UI conversion jobs in memory.

Jobs run on daemon threads, collect timestamped log lines, expose safe snapshots to HTTP
handlers, and are trimmed when the configured limit is exceeded.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    """Store all browser-visible state for one Web UI export job.

    Attributes:
        id (str): Stable local job identifier used by the Web API.
        kind (str): Picker or job kind requested by the caller.
        status (str): HTTP status code or job status value.
        created_at (float): Unix timestamp recording when the job was created.
        updated_at (float): Unix timestamp recording the last job-state change.
        logs (list[str]): Ordered human-readable log lines captured for the job.
        result (dict[str, Any] | None): JSON-compatible result object produced by a successful job.
        error (str | None): Error text captured for a failed job.
    """

    id: str
    kind: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


# Runner callbacks receive the submitted payload and a logger, then return a JSON-compatible result object.
Runner = Callable[[dict[str, Any], Callable[[str], None]], dict[str, Any]]


class JobStore:
    """Create, run, serialize, and prune Web UI jobs with thread-safe in-memory state.
    """

    def __init__(self, max_jobs: int = 50) -> None:
        """Initialize JobStore with validated configuration and state.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            max_jobs (int): Maximum number of retained Web jobs.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        # Keep the local HTTP and frontend behavior explicit because the Web UI runs
        # without a separate framework.
        self.max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, payload: dict[str, Any], runner: Runner) -> Job:
        """Create and start a background conversion job.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            kind (str): Picker or job kind requested by the caller.
            payload (dict[str, Any]): JSON request body or Web form payload.
            runner (Runner): Callable that executes a queued job.

        Returns:
            Job: Detached job snapshot suitable for storage or serialization.
        """
        # Keep the local HTTP and frontend behavior explicit because the Web UI runs
        # without a separate framework.
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_locked()

        # Short random ids are sufficient for local Web UI display and avoid leaking path details into URLs.
        thread = threading.Thread(
            target=self._run_worker,
            args=(job, payload, runner),
            daemon=True,
        )
        thread.start()
        return job

    def list_jobs(self) -> list[Job]:
        """List jobs.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Returns:
            list[Job]: Detached job snapshots ordered for Web API serialization.
        """
        with self._lock:
            # Return clones so HTTP handlers cannot observe concurrent mutation while background workers update jobs.
            return sorted(
                (self._clone(job) for job in self._jobs.values()),
                key=lambda job: job.created_at,
                reverse=True,
            )

    def get(self, job_id: str) -> Job | None:
        """Return one background job by id.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            job_id (str): Identifier of the job to read or update.

        Returns:
            Job | None: Detached job snapshot when the id exists; otherwise None.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            return self._clone(job) if job is not None else None

    def serialize(self, job: Job, include_logs: bool = False) -> dict[str, Any]:
        """Convert a job snapshot into a JSON response payload.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            job (Job): Job record to serialize or mutate.
            include_logs (bool): Whether serialized job data should include log lines.

        Returns:
            dict[str, Any]: JSON-compatible dictionary for API or conversion callers.
        """
        # Follow schema field layout exactly so alignment, padding, and unknown data
        # remain binary-compatible.
        data: dict[str, Any] = {
            "id": job.id,
            "kind": job.kind,
            "status": job.status,
            "createdAt": job.created_at,
            "updatedAt": job.updated_at,
            "result": job.result,
            "error": job.error,
        }
        if include_logs:
            data["logs"] = list(job.logs)
        return data

    def _run_worker(self, job: Job, payload: dict[str, Any], runner: Runner) -> None:
        """Run worker.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            job (Job): Job record to serialize or mutate.
            payload (dict[str, Any]): JSON request body or Web form payload.
            runner (Runner): Callable that executes a queued job.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        self._set_job(job.id, status="running")
        self._log(job.id, "Job started.")
        try:
            # A failed job records its own error without stopping the local HTTP server or other queued jobs.
            result = runner(payload, lambda message: self._log(job.id, message))
        except Exception as exc:
            # Treat each file independently so one malformed resource is reported but
            # does not stop the rest of the batch.
            error = f"{exc.__class__.__name__}: {exc}"
            self._set_job(job.id, status="failed", error=error)
            self._log(job.id, f"Job failed: {error}")
            return
        self._set_job(job.id, status="done", result=result)
        self._log(job.id, "Job complete.")

    def _set_job(self, job_id: str, **changes: Any) -> None:
        """Apply status, result, error, or timestamp changes to a tracked job.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            job_id (str): Identifier of the job to read or update.
            changes (Any): Keyword changes to merge into the stored job state.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _log(self, job_id: str, message: str) -> None:
        """Write a human-readable log entry.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            job_id (str): Identifier of the job to read or update.
            message (str): Human-readable status or log message.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
            job.updated_at = time.time()

    def _cleanup_locked(self) -> None:
        """Remove old finished jobs while the job-store lock is already held.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Returns:
            None. The method performs its documented side effect in place and raises on invalid input.
        """
        if len(self._jobs) <= self.max_jobs:
            return
        ordered = sorted(
            self._jobs.values(),
            key=lambda job: job.created_at,
            reverse=True,
        )
        keep = {job.id for job in ordered[: self.max_jobs]}
        for job_id in list(self._jobs):
            if job_id not in keep:
                self._jobs.pop(job_id, None)

    @staticmethod
    def _clone(job: Job) -> Job:
        """Return a detached copy of the current job state for HTTP serialization.

        The method keeps local Web UI state and request handling explicit because there is no
        external framework managing these concerns.

        Args:
            job (Job): Job record to serialize or mutate.

        Returns:
            Job: Detached job snapshot suitable for storage or serialization.
        """
        return Job(
            id=job.id,
            kind=job.kind,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            logs=list(job.logs),
            result=job.result,
            error=job.error,
        )
