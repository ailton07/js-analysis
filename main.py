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


@cli.command("test-tools")
def test_tools() -> None:
    """Verify all required tools are installed and reachable."""
    import subprocess
    import sys

    checks = [
        ("katana",      ["katana", "-version"]),
        ("notify",      ["notify", "-version"]),
        ("gitleaks",    ["gitleaks", "version"]),
        ("trufflehog",  ["trufflehog", "--version"]),
        ("waymore",     ["waymore", "--version"]),
    ]

    results: list[str] = []
    all_ok = True
    for name, cmd in checks:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = (result.stdout or result.stderr).strip().splitlines()
            version = lines[0] if lines else "(no version output)"
            console.print(f"  [green]OK[/green]  {name:<12} {version}")
            results.append(f"OK  {name:<12} {version}")
        except FileNotFoundError:
            console.print(f"  [red]MISSING[/red]  {name}")
            results.append(f"MISSING  {name}")
            all_ok = False
        except Exception as exc:
            console.print(f"  [yellow]ERROR[/yellow]  {name:<12} {exc}")
            results.append(f"ERROR  {name:<12} {exc}")
            all_ok = False

    status = "All tools OK" if all_ok else "Some tools MISSING"
    report = f"[test-tools] {status}\n" + "\n".join(results)
    try:
        subprocess.run(["notify", "-silent"], input=report.encode(),
                       capture_output=True, check=False, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    cli()
