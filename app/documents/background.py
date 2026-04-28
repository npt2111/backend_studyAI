import os
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

_MAX_WORKERS = max(1, int(os.getenv("SUMMARY_WORKER_THREADS", "2")))
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
_LOCK = Lock()
_RUNNING_JOB_IDS = set()


def submit_summary_job(job_id: str) -> bool:
    with _LOCK:
        if job_id in _RUNNING_JOB_IDS:
            return False
        _RUNNING_JOB_IDS.add(job_id)

    def _runner():
        try:
            from .services import process_summary_job
            process_summary_job(job_id)
        finally:
            with _LOCK:
                _RUNNING_JOB_IDS.discard(job_id)

    _EXECUTOR.submit(_runner)
    return True
