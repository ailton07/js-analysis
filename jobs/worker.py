import time

from rich.console import Console

from jobs import job_manager
from pipeline import run_pipeline

console = Console()
_POLL_INTERVAL = 10  # seconds between queue checks


def run_worker() -> None:
    console.print("[bold green]Worker started — polling for jobs...")
    while True:
        job = job_manager.next_job()
        if not job:
            time.sleep(_POLL_INTERVAL)
            continue

        job_id = job["id"]
        domain = job["target_domain"]
        config_path = job["config_path"]

        console.print(f"[cyan]Job {job_id}: {domain}")
        job_manager.mark_running(job_id)

        try:
            run_pipeline(config_path)
            job_manager.mark_done(job_id)
            console.print(f"[green]Job {job_id} done")
        except Exception as exc:
            job_manager.mark_failed(job_id, str(exc))
            console.print(f"[red]Job {job_id} failed: {exc}")
