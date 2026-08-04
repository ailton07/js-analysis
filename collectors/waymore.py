import re
import subprocess
import urllib.parse
from pathlib import Path

_JS_RE = re.compile(r'\.js(\?|$)', re.IGNORECASE)
_STATIC_RE = re.compile(
    r'\.(css|png|jpe?g|gif|svg|ico|woff2?|ttf|eot|pdf|zip|gz|map|webp|mp4|webm)(\?|$)',
    re.IGNORECASE,
)


def collect(
    domain: str, output_dir: Path, timeout: int = 600, scope: list[str] | None = None
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"waymore_{domain}.txt"

    # waymore's -i accepts a single domain OR a file listing multiple domains
    # (one per line), merging results into the same -oU output file. Use the
    # latter when scope has more than just the primary domain, so URLs are
    # collected for every in-scope domain, not just `domain`.
    domains = scope or [domain]
    if len(domains) > 1:
        domains_file = output_dir / f"waymore_{domain}_domains.txt"
        domains_file.write_text("\n".join(domains) + "\n")
        input_arg = str(domains_file)
    else:
        input_arg = domain

    try:
        subprocess.run(
            ["waymore", "-i", input_arg, "-mode", "U", "-oU", str(output_file)],
            timeout=timeout,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("waymore not found — install with: pip install waymore")
    except subprocess.TimeoutExpired:
        pass  # partial results are still useful

    if not output_file.exists():
        return []

    return [
        u.strip()
        for u in output_file.read_text().splitlines()
        if u.strip() and _JS_RE.search(u)
    ]


def collect_seeds(domain: str, output_dir: Path, max_seeds: int = 300) -> list[str]:
    """Return unique page URLs from the waymore output file, for use as katana seeds.

    Deduplicates by (host, path) — strips query strings — and excludes static
    assets so katana gets navigable page entry points, not binary files.
    """
    output_file = output_dir / f"waymore_{domain}.txt"
    if not output_file.exists():
        return []

    seen: set[tuple[str, str]] = set()
    seeds: list[str] = []

    for raw in output_file.read_text().splitlines():
        u = raw.strip()
        if not u or _JS_RE.search(u) or _STATIC_RE.search(u):
            continue
        try:
            p = urllib.parse.urlparse(u)
            key = (p.netloc, p.path.rstrip("/"))
            if key in seen:
                continue
            seen.add(key)
            seeds.append(f"{p.scheme}://{p.netloc}{p.path}")
        except Exception:
            continue
        if len(seeds) >= max_seeds:
            break

    return seeds
