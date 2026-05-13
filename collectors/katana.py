import os
import re
import subprocess
import tempfile

_JS_RE = re.compile(r'\.js(\?|$)', re.IGNORECASE)


def collect(
    target_urls: list[str] | str,
    depth: int = 2,
    js_crawl: bool = True,
    timeout: int = 300,
    proxy: str = None,
) -> list[str]:
    if isinstance(target_urls, str):
        target_urls = [target_urls]

    list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    try:
        list_file.write("\n".join(target_urls))
        list_file.close()
        return _run(list_file.name, depth, js_crawl, timeout, proxy)
    finally:
        os.unlink(list_file.name)


def _run(
    list_path: str,
    depth: int,
    js_crawl: bool,
    timeout: int,
    proxy: str | None,
) -> list[str]:
    cmd = [
        "katana",
        "-list", list_path,
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
