import os
import subprocess
import tempfile
import time
from urllib.parse import urlparse

# Above this many unique hosts, a batch is the full waymore URL list, not
# katana's seed set — see the retry note in filter_live below.
_SEED_RETRY_THRESHOLD = 50


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

        # A small batch (katana seeds) coming back with zero live hosts is
        # often a transient hiccup — a WAF/CF challenge on the probe request,
        # a cold DNS cache — rather than every host actually being dead, so
        # it's worth a couple of short retries. Skip this for the full
        # waymore URL list: retrying thousands of URLs 2-3x over would
        # multiply outbound requests against those hosts and risks tripping
        # the target's own rate limiting / WAF.
        retries = 0
        while (
            live_hosts is not None
            and not live_hosts
            and len(hosts_to_urls) <= _SEED_RETRY_THRESHOLD
            and retries < 2
        ):
            time.sleep(3)
            live_hosts = _run(list_file.name, timeout, concurrency, probe_timeout)
            retries += 1
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
        "-t", str(concurrency),
        "-silent",
        "-no-color",
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

    if result.returncode != 0:
        # A CLI error here (bad flag, incompatible httpx version, crash) still
        # prints to stdout with a nonzero exit — never let that be silently
        # parsed as "zero hosts are live". Raise so the caller falls back to
        # the unfiltered list instead of nuking every URL.
        detail = (result.stderr or result.stdout).strip().splitlines()[:1]
        raise RuntimeError(f"httpx exited {result.returncode}: {detail[0] if detail else 'no output'}")

    live = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        live.add(line.split("://", 1)[-1].split("/")[0])
    return live
