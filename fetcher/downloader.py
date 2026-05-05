import hashlib
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from db import store

VALID_CONTENT_TYPES = {
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
    "text/plain",
}

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _make_session(timeout: int) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers["User-Agent"] = random.choice(_USER_AGENTS)
    session.timeout = timeout
    return session


def _fetch_sourcemaps(
    js_url: str,
    resp_headers: dict,
    session: requests.Session,
    raw_dir: Path,
    target_id: int,
) -> list[dict]:
    """Try to fetch .js.map and extract original source files from sourcesContent."""
    map_url = (
        resp_headers.get("SourceMap")
        or resp_headers.get("X-SourceMap")
        or js_url + ".map"
    )
    results = []
    try:
        map_resp = session.get(map_url, timeout=10)
        if map_resp.status_code != 200:
            return results
        map_data = map_resp.json()
    except Exception:
        return results

    sources_content = map_data.get("sourcesContent") or []
    source_names = map_data.get("sources") or []

    for i, src in enumerate(sources_content):
        if not src:
            continue
        name = source_names[i] if i < len(source_names) else f"source_{i}"
        src_bytes = src.encode("utf-8", errors="replace")
        src_hash = hashlib.sha256(src_bytes).hexdigest()
        src_url = f"{js_url}#sourcemap:{name}"

        already_known = store.is_hash_known(src_hash)
        out_path = raw_dir / f"{src_hash}.js"
        if not out_path.exists():
            out_path.write_bytes(src_bytes)

        store.save_js_file(src_hash, src_url, "sourcemap", target_id, len(src_bytes))
        results.append({"hash": src_hash, "url": src_url, "already_known": already_known})

    return results


def _fetch_one(
    url: str,
    session: requests.Session,
    raw_dir: Path,
    delay: float,
    jitter: float,
    max_bytes: int,
    target_id: int,
) -> dict | None:
    time.sleep(delay + random.uniform(0, jitter))

    try:
        resp = session.get(url, stream=True, timeout=session.timeout)
    except Exception:
        return None

    if resp.status_code != 200:
        return None

    ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if ct and ct not in VALID_CONTENT_TYPES:
        return None

    content = b""
    for chunk in resp.iter_content(chunk_size=8192):
        content += chunk
        if len(content) > max_bytes:
            return None

    file_hash = hashlib.sha256(content).hexdigest()
    already_known = store.is_hash_known(file_hash)

    out_path = raw_dir / f"{file_hash}.js"
    if not out_path.exists():
        out_path.write_bytes(content)

    store.save_js_file(file_hash, url, "fetcher", target_id, len(content))

    sourcemap_files = _fetch_sourcemaps(url, resp.headers, session, raw_dir, target_id)

    return {
        "hash": file_hash,
        "url": url,
        "already_known": already_known,
        "sourcemap_files": sourcemap_files,
    }


def fetch_all(
    urls: list[str],
    target_id: int,
    raw_dir: Path,
    config: dict,
) -> list[dict]:
    cfg = config.get("fetcher", {})
    delay = cfg.get("delay", 1.5)
    jitter = cfg.get("jitter", 0.5)
    max_concurrent = cfg.get("max_concurrent", 3)
    timeout = cfg.get("timeout", 15)
    max_bytes = int(cfg.get("max_content_mb", 10) * 1024 * 1024)

    raw_dir.mkdir(parents=True, exist_ok=True)
    session = _make_session(timeout)

    results = []
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(
                _fetch_one, url, session, raw_dir, delay, jitter, max_bytes, target_id
            ): url
            for url in urls
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    return results
