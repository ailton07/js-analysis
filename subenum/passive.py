import os
import subprocess
import tempfile

# Common two-label public suffixes — without these, the naive "last two
# labels" apex heuristic below would truncate e.g. "sub.example.co.uk" down
# to "co.uk" instead of "example.co.uk".
_MULTI_PART_TLDS = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "net.uk",
    "com.au", "net.au", "org.au", "com.br", "net.br",
    "com.mx", "com.ar", "com.co", "co.jp", "ne.jp", "or.jp",
    "co.in", "net.in", "co.nz", "co.za", "com.sg", "com.tr",
    "com.tw", "co.kr",
}


def _apex(domain: str) -> str:
    domain = domain.strip().lower().lstrip("*.").rstrip(".")
    labels = domain.split(".")
    if len(labels) <= 2:
        return domain
    last_two = ".".join(labels[-2:])
    if last_two in _MULTI_PART_TLDS and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def collect(domain: str, timeout: int = 900, scope: list[str] | None = None) -> list[str]:
    # Default bumped from 300s: -dL across many apex domains is slow — each
    # passive source is queried per apex, and per-source rate limiting adds
    # up fast with a large multi-domain scope.
    # subfinder enumerates subdomains OF an apex — feeding it entries that are
    # already subdomains (as a bug bounty program's scope list often is, e.g.
    # 42 mixed apex/subdomain entries) makes -dL fail outright instead of
    # just returning nothing useful. Reduce to unique apex domains first.
    domains = scope or [domain]
    apexes = sorted({_apex(d) for d in domains if d and d.strip()}) or [_apex(domain)]

    if len(apexes) > 1:
        list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        try:
            list_file.write("\n".join(apexes))
            list_file.close()
            cmd = ["subfinder", "-dL", list_file.name, "-silent"]
            return _run(cmd, timeout)
        finally:
            os.unlink(list_file.name)
    return _run(["subfinder", "-d", apexes[0], "-silent"], timeout)


def _run(cmd: list[str], timeout: int) -> list[str]:
    try:
        result = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "subfinder not found — install with: "
            "go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"
        )
    except subprocess.TimeoutExpired:
        return []

    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})
