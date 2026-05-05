from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from rich.console import Console

from db import store
from jobs import job_manager

console = Console()


def _load_targets() -> list[dict]:
    targets = []
    for path in Path("targets").glob("*.yaml"):
        try:
            cfg = yaml.safe_load(path.read_text())
            if not cfg.get("enabled", True):
                console.print(f"  [dim]{path.name}: disabled, skipping")
                continue
            cfg["_path"] = str(path)
            targets.append(cfg)
        except Exception as exc:
            console.print(f"[red]Could not load {path}: {exc}")
    return targets


def _schedule_target(scheduler: BlockingScheduler, target: dict) -> None:
    domain = target.get("domain", "unknown")
    cron = target.get("schedule")
    config_path = target["_path"]

    if not cron or cron is False:
        console.print(f"  [dim]{domain}: one-shot (run manually)")
        return

    parts = cron.split()
    if len(parts) != 5:
        console.print(f"  [red]{domain}: invalid cron '{cron}'")
        return

    minute, hour, day, month, day_of_week = parts
    scheduler.add_job(
        job_manager.enqueue,
        "cron",
        args=[domain, config_path],
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        id=f"target_{domain}",
        replace_existing=True,
    )
    console.print(f"  [green]{domain}[/green] → [{cron}]")


def run_scheduler() -> None:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    store.init(data_dir / "findings.db")

    scheduler = BlockingScheduler()
    targets = _load_targets()

    console.print(f"[bold cyan]Scheduling {len(targets)} target(s)...")
    for target in targets:
        _schedule_target(scheduler, target)

    console.print("[bold green]Scheduler running.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        console.print("[yellow]Scheduler stopped.")
