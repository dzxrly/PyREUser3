"""Thread-safe in-memory job store for Web UI tasks."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    """Record describing one Web UI export job."""

    id: str
    kind: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


# Keep this implementation detail explicit.
Runner = Callable[[dict[str, Any], Callable[[str], None]], dict[str, Any]]


class JobStore:
    """Thread-safe in-memory repository for Web UI jobs."""

    def __init__(self, max_jobs: int = 50) -> None:
        """Initialize the instance."""
        # Keep Web UI behavior explicit and predictable.
        self.max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, payload: dict[str, Any], runner: Runner) -> Job:
        """Start start."""
        # Keep Web UI behavior explicit and predictable.
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_locked()

        # Keep this implementation detail explicit.
        thread = threading.Thread(
            target=self._run_worker,
            args=(job, payload, runner),
            daemon=True,
        )
        thread.start()
        return job

    def list_jobs(self) -> list[Job]:
        """List jobs."""
        with self._lock:
            # Keep this implementation detail explicit.
            return sorted(
                (self._clone(job) for job in self._jobs.values()),
                key=lambda job: job.created_at,
                reverse=True,
            )

    def get(self, job_id: str) -> Job | None:
        """Get get."""
        with self._lock:
            job = self._jobs.get(job_id)
            return self._clone(job) if job is not None else None

    def serialize(self, job: Job, include_logs: bool = False) -> dict[str, Any]:
        """Serialize serialize."""
        # Preserve field layout details for binary compatibility.
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
        """Internal helper for run worker."""
        self._set_job(job.id, status="running")
        self._log(job.id, "Job started.")
        try:
            # Keep this implementation detail explicit.
            result = runner(payload, lambda message: self._log(job.id, message))
        except Exception as exc:
            # Record per-file failures without stopping the whole batch.
            error = f"{exc.__class__.__name__}: {exc}"
            self._set_job(job.id, status="failed", error=error)
            self._log(job.id, f"Job failed: {error}")
            return
        self._set_job(job.id, status="done", result=result)
        self._log(job.id, "Job complete.")

    def _set_job(self, job_id: str, **changes: Any) -> None:
        """Internal helper for set job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _log(self, job_id: str, message: str) -> None:
        """Internal helper for log."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
            job.updated_at = time.time()

    def _cleanup_locked(self) -> None:
        """Internal helper for cleanup locked."""
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
        """Internal helper for clone."""
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
