import re
import subprocess

_JS_RE = re.compile(r'\.js(\?|$)', re.IGNORECASE)


def collect(
    target_url: str,
    depth: int = 2,
    js_crawl: bool = True,
    timeout: int = 300,
    proxy: str = None,
) -> list[str]:
    cmd = [
        "katana",
        "-u", target_url,
        "-d", str(depth),
        "-silent",
        "-no-color",
    ]
    if js_crawl:
        cmd.append("-jc")
    if proxy:
        cmd.extend(["-proxy", proxy])

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
            "katana not found — install with: "
            "go install github.com/projectdiscovery/katana/cmd/katana@latest"
        )
    except subprocess.TimeoutExpired:
        return []

    return [
        u.strip()
        for u in result.stdout.splitlines()
        if u.strip() and _JS_RE.search(u)
    ]
