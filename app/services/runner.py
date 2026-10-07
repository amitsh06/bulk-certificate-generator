"""Runs jobs outside the request.

The API answers with 202 Accepted straight away and the work happens on a small
thread pool. Everything goes through submit(job_id), so swapping this for a real
queue (Celery, RQ, a cloud queue) later only means changing this one class.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from app.services.processor import process_job

logger = logging.getLogger(__name__)


def _run_safely(job_id: str) -> None:
    try:
        process_job(job_id)
    except Exception:  # never let a worker thread die silently
        logger.exception("Job %s crashed; it will be picked up again on the next restart", job_id)


class JobRunner:
    def __init__(self, mode: str = "background", workers: int = 2):
        if mode not in {"background", "sync"}:
            raise ValueError("processing_mode must be 'background' or 'sync'")
        self.mode = mode
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="certgen") if mode == "background" else None

    def submit(self, job_id: str) -> None:
        if self._executor is None:
            _run_safely(job_id)
        else:
            self._executor.submit(_run_safely, job_id)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
