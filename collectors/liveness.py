import os
import subprocess
import tempfile
from urllib.parse import urlparse


def filter_live(
    urls: list[str],
    timeout: int = 300,
    concurrency: int = 50,
    probe_timeout: int = 5,
) -> list[str]:
    """Drop URLs whose host never answers (e.g. decommissioned waymore/wayback
    subdomains stuck in SYN_SENT), so they never reach katana or the fetcher.

    Probes unique hosts, not every URL — the failure mode here is TCP-level
    (host unreachable), not per-path, so deduping to hosts first is both
    cheaper and sufficient. Fails open (returns the input unchanged) if httpx
    times out, so a slow probe never zeroes out an otherwise-good URL list.
    """
    if not urls:
        return []

    hosts_to_urls: dict[str, list[str]] = {}
    for u in urls:
        host = urlparse(u).netloc
        if host:
            hosts_to_urls.setdefault(host, []).append(u)

    if not hosts_to_urls:
        return urls

    list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    try:
        list_file.write("\n".join(hosts_to_urls))
        list_file.close()
        live_hosts = _run(list_file.name, timeout, concurrency, probe_timeout)
    finally:
        os.unlink(list_file.name)

    if live_hosts is None:
        return urls

    return [u for host in live_hosts for u in hosts_to_urls.get(host, [])]


def _run(
    list_path: str, timeout: int, concurrency: int, probe_timeout: int
) -> set[str] | None:
    cmd = [
        "httpx",
        "-l", list_path,
        "-mc", "200,301,302,403",
        "-timeout", str(probe_timeout),
        "-c", str(concurrency),
        "-silent",
    ]
    try:
        result = subprocess.run(
            cmd, timeout=timeout, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise RuntimeError(
            "httpx not found — install with: "
            "go install github.com/projectdiscovery/httpx/cmd/httpx@latest"
        )
    except subprocess.TimeoutExpired:
        return None

    live = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        live.add(line.split("://", 1)[-1].split("/")[0])
    return live
