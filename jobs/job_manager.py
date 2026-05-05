from db import store


def enqueue(target_domain: str, config_path: str) -> int:
    return store.enqueue_job(target_domain, config_path)


def next_job() -> dict | None:
    return store.next_pending_job()


def mark_running(job_id: int) -> None:
    store.update_job(job_id, "running")


def mark_done(job_id: int) -> None:
    store.update_job(job_id, "done")


def mark_failed(job_id: int, error: str) -> None:
    store.update_job(job_id, "failed", error)
