from pathlib import Path

from db import store

_TARGETS_DIR = Path("targets")


def enqueue(target_domain: str, config_path: str) -> int:
    # The worker/scheduler containers only ever see targets/ (mounted at
    # /app/targets), never the host filesystem — store a targets/-relative
    # path regardless of what was passed in, so a job enqueued from the host
    # with an absolute host path still resolves inside the worker container.
    normalized_path = str(_TARGETS_DIR / Path(config_path).name)
    return store.enqueue_job(target_domain, normalized_path)


def next_job() -> dict | None:
    return store.next_pending_job()


def mark_running(job_id: int) -> None:
    store.update_job(job_id, "running")


def mark_done(job_id: int) -> None:
    store.update_job(job_id, "done")


def mark_failed(job_id: int, error: str) -> None:
    store.update_job(job_id, "failed", error)
