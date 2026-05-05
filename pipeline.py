import shutil
from pathlib import Path

import yaml
from rich.console import Console

from collectors import katana, waymore
from db import store
from fetcher.downloader import fetch_all
from normalizer.js_normalizer import normalize
from scanners import gitleaks_runner, notifier, trufflehog_runner

console = Console()


def load_global_config() -> dict:
    path = Path("config.yaml")
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def run_pipeline(target_config_path: str) -> None:
    global_cfg = load_global_config()
    target_cfg = yaml.safe_load(Path(target_config_path).read_text())

    domain = target_cfg["domain"]
    program = target_cfg.get("program", domain)

    data_dir = Path(global_cfg.get("data_dir", "data"))
    reports_dir = Path(global_cfg.get("reports_dir", "reports"))
    tmp_dir = data_dir / "tmp"
    raw_dir = data_dir / "raw_js"
    norm_dir = data_dir / "normalized_js"

    for d in (tmp_dir, raw_dir, norm_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    store.init(data_dir / "findings.db")
    target_id = store.get_or_create_target(domain, program, target_config_path)

    console.rule(f"[bold cyan]{domain}")

    # ── 1. Collect ──────────────────────────────────────────────────────────
    console.print("[yellow]Collecting JS URLs...")
    urls: set[str] = set()

    try:
        w_urls = waymore.collect(domain, tmp_dir)
        console.print(f"  waymore : {len(w_urls):>5} URLs")
        urls.update(w_urls)
    except RuntimeError as e:
        console.print(f"  [red]waymore skipped: {e}")

    try:
        k_cfg = global_cfg.get("collectors", {}).get("katana", {})
        k_urls = katana.collect(
            f"https://{domain}",
            depth=target_cfg.get("crawl_depth", k_cfg.get("depth", 2)),
            js_crawl=k_cfg.get("js_crawl", True),
            timeout=k_cfg.get("timeout", 300),
        )
        console.print(f"  katana  : {len(k_urls):>5} URLs")
        urls.update(k_urls)
    except RuntimeError as e:
        console.print(f"  [red]katana skipped: {e}")

    # Apply scope / exclude filters from target config
    exclude = target_cfg.get("exclude", [])
    scope = target_cfg.get("scope", [])
    if scope:
        urls = {u for u in urls if any(s in u for s in scope)}
    if exclude:
        urls = {u for u in urls if not any(e in u for e in exclude)}

    url_list = list(urls)[: target_cfg.get("max_urls", 5000)]
    console.print(f"  total   : {len(url_list):>5} (after dedup / filters)")

    # ── 2. Fetch ─────────────────────────────────────────────────────────────
    console.print("[yellow]Fetching JS files...")
    fetched = fetch_all(url_list, target_id, raw_dir, global_cfg)
    new_files = [f for f in fetched if not f["already_known"]]
    console.print(f"  fetched {len(fetched)}, new {len(new_files)}")

    # ── 3. Normalize new files only ──────────────────────────────────────────
    console.print("[yellow]Normalizing...")
    normalized = 0
    for f in new_files:
        in_path = raw_dir / f"{f['hash']}.js"
        out_path = norm_dir / f"{f['hash']}.js"
        if in_path.exists() and not out_path.exists():
            if normalize(in_path, out_path):
                normalized += 1
        for sm in f.get("sourcemap_files", []):
            if not sm["already_known"]:
                sm_in = raw_dir / f"{sm['hash']}.js"
                sm_out = norm_dir / f"{sm['hash']}.js"
                if sm_in.exists() and not sm_out.exists():
                    if normalize(sm_in, sm_out):
                        normalized += 1
    console.print(f"  normalized {normalized} files")

    # ── 4. Build url_map for scanners ────────────────────────────────────────
    url_map: dict[str, str] = {}
    for f in fetched:
        url_map[f["hash"]] = f["url"]
        for sm in f.get("sourcemap_files", []):
            url_map[sm["hash"]] = sm["url"]

    # ── 5. Scan ───────────────────────────────────────────────────────────────
    console.print("[yellow]Scanning...")
    all_findings: list[dict] = []

    try:
        gl = gitleaks_runner.scan(
            norm_dir, target_id, url_map,
            reports_dir / f"gitleaks_{domain}.csv",
        )
        console.print(f"  gitleaks   : {len(gl):>4} findings")
        all_findings.extend(gl)
    except RuntimeError as e:
        console.print(f"  [red]gitleaks skipped: {e}")

    try:
        th = trufflehog_runner.scan(norm_dir, target_id, url_map)
        console.print(f"  trufflehog : {len(th):>4} findings")
        all_findings.extend(th)
    except RuntimeError as e:
        console.print(f"  [red]trufflehog skipped: {e}")

    # ── 6. Persist + notify ───────────────────────────────────────────────────
    new_count = 0
    for finding in all_findings:
        is_new = store.save_finding(finding)
        if is_new:
            new_count += 1
            if target_cfg.get("notify", True) and notifier.should_notify(finding, global_cfg):
                notifier.notify(finding)

    console.print(f"[bold green]Done — {new_count} new findings.")

    # ── 7. Clean normalized dir (findings are in DB) ──────────────────────────
    shutil.rmtree(norm_dir, ignore_errors=True)
    norm_dir.mkdir(parents=True, exist_ok=True)
