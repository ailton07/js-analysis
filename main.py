from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("target", type=click.Path(exists=True))
def run(target: str) -> None:
    """Run the full pipeline for a single TARGET yaml file."""
    from db import store
    from pipeline import run_pipeline

    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    store.init(data_dir / "findings.db")
    run_pipeline(target)


@cli.command()
def worker() -> None:
    """Start the job worker (polls the queue and runs pipelines)."""
    from db import store
    from jobs.worker import run_worker

    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    store.init(data_dir / "findings.db")
    run_worker()


@cli.command()
def scheduler() -> None:
    """Start the scheduler (enqueues jobs based on target cron schedules)."""
    from scheduler import run_scheduler

    run_scheduler()


@cli.command()
@click.argument("domain")
@click.argument("config_path", type=click.Path(exists=True))
def enqueue(domain: str, config_path: str) -> None:
    """Manually enqueue a job for DOMAIN using CONFIG_PATH."""
    from db import store
    from jobs import job_manager

    data_dir = Path("data")
    store.init(data_dir / "findings.db")
    job_id = job_manager.enqueue(domain, config_path)
    console.print(f"[green]Job {job_id} enqueued for {domain}")


if __name__ == "__main__":
    cli()
