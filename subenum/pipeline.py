import json
from pathlib import Path

import yaml
from rich.console import Console

from db import store
from netcheck import check_vpn
from scanners import notifier
from subenum import httpx_probe, passive, resolve, tls_scrape

console = Console()


def load_global_config() -> dict:
    path = Path("subenum-config.yaml")
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def _apply_scope(hosts: set[str], target_cfg: dict) -> set[str]:
    scope = target_cfg.get("scope", [])
    exclude = target_cfg.get("exclude", [])
    if scope:
        hosts = {h for h in hosts if any(s in h for s in scope)}
    if exclude:
        hosts = {h for h in hosts if not any(e in h for e in exclude)}
    return hosts


def run_subenum(target_config_path: str) -> None:
    global_cfg = load_global_config()
    target_cfg = yaml.safe_load(Path(target_config_path).read_text())

    if not target_cfg.get("enabled", True):
        raise SystemExit(
            f"Target '{target_config_path}' is disabled (enabled: false). "
            "Copy it and set enabled: true."
        )

    check_vpn()

    domain = target_cfg["domain"]
    data_dir = Path(global_cfg.get("data_dir", "data"))
    out_dir = data_dir / "subdomains" / domain
    out_dir.mkdir(parents=True, exist_ok=True)

    store.init(data_dir / "findings.db")
    target_id = store.get_or_create_target(
        domain, target_cfg.get("program", domain), target_config_path
    )

    verbose = target_cfg.get("verbose", False)

    def vprogress(text: str) -> None:
        if verbose:
            notifier.progress(text)

    console.rule(f"[bold cyan]{domain} — subdomain enumeration")
    vprogress(f"[{domain}] subdomain enum started")

    # ── 1. Passive discovery ────────────────────────────────────────────────
    console.print("[yellow]Passive discovery...")
    try:
        hosts = set(passive.collect(domain, scope=target_cfg.get("scope", [])))
    except RuntimeError as e:
        raise SystemExit(f"subfinder failed: {e}")
    console.print(f"  subfinder : {len(hosts):>5} hosts")

    hosts = _apply_scope(hosts, target_cfg)
    console.print(f"  in scope  : {len(hosts):>5}")
    vprogress(f"[{domain}] {len(hosts)} hosts from passive discovery")

    # ── 2. Resolve + wildcard filter ────────────────────────────────────────
    resolve_cfg = global_cfg.get("resolve", {})
    resolved: dict[str, dict] = {}

    if resolve_cfg.get("dnsx", True) and hosts:
        console.print("[yellow]Resolving...")
        try:
            for r in resolve.resolve(sorted(hosts)):
                resolved[r["subdomain"]] = {**r, "source": "passive"}
            console.print(f"  resolved  : {len(resolved):>5}")
        except RuntimeError as e:
            console.print(f"  [red]dnsx skipped: {e}")
            resolved = {h: {"subdomain": h, "resolved_ip": None, "source": "passive"} for h in hosts}
    else:
        resolved = {h: {"subdomain": h, "resolved_ip": None, "source": "passive"} for h in hosts}

    # ── 3. TLS SAN follow-up (new names only, then resolved individually) ──
    if resolve_cfg.get("tlsx", True) and resolved:
        console.print("[yellow]TLS SAN scraping...")
        try:
            new_hosts = set(tls_scrape.scrape(sorted(resolved))) - set(resolved)
            new_hosts = _apply_scope(new_hosts, target_cfg)
            if new_hosts:
                console.print(f"  tlsx new  : {len(new_hosts):>5} additional hosts")
                for r in resolve.resolve(sorted(new_hosts)):
                    resolved[r["subdomain"]] = {**r, "source": "tlsx"}
        except RuntimeError as e:
            console.print(f"  [red]tlsx skipped: {e}")

    vprogress(f"[{domain}] {len(resolved)} candidate subdomains after resolve/tlsx")

    # ── 4. Live probe ───────────────────────────────────────────────────────
    probe_cfg = global_cfg.get("probe", {})
    live_by_host: dict[str, dict] = {}

    if probe_cfg.get("httpx", True) and resolved:
        console.print("[yellow]Probing live hosts...")
        try:
            for p in httpx_probe.probe(sorted(resolved)):
                live_by_host[p["subdomain"]] = p
        except RuntimeError as e:
            console.print(f"  [red]httpx skipped: {e}")
    console.print(f"  live      : {len(live_by_host):>5}")

    # ── 5. Persist + notify ─────────────────────────────────────────────────
    notify_cfg = global_cfg.get("notify", {})
    new_live_only = notify_cfg.get("new_live_only", True)

    new_count = 0
    all_hosts: list[str] = []
    live_hosts: list[str] = []
    live_records: list[dict] = []

    for host, info in sorted(resolved.items()):
        live_info = live_by_host.get(host)
        record = {
            "target_id": target_id,
            "subdomain": host,
            "source": info.get("source", "passive"),
            "resolved_ip": info.get("resolved_ip"),
            "alive": 1 if live_info else 0,
            "http_status": live_info.get("http_status") if live_info else None,
            "title": live_info.get("title") if live_info else None,
            "tech": ", ".join(live_info.get("tech", [])) if live_info else None,
        }
        is_new = store.save_subdomain(record)
        if is_new:
            new_count += 1

        all_hosts.append(host)
        if live_info:
            live_hosts.append(host)
            live_records.append(record)

        should_notify = target_cfg.get("notify", True) and is_new
        if should_notify and new_live_only and not live_info:
            should_notify = False
        if should_notify:
            notifier.notify_subdomain(record)

    (out_dir / "all.txt").write_text("\n".join(all_hosts) + ("\n" if all_hosts else ""))
    (out_dir / "live.txt").write_text("\n".join(live_hosts) + ("\n" if live_hosts else ""))
    (out_dir / "live.json").write_text(json.dumps(live_records, indent=2, sort_keys=True))

    console.print(
        f"[bold green]Done — {len(resolved)} subdomains "
        f"({len(live_hosts)} live, {new_count} new)."
    )
    vprogress(
        f"[{domain}] done — {len(resolved)} subdomains "
        f"({len(live_hosts)} live, {new_count} new)"
    )
