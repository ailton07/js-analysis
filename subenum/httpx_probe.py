import json
import os
import subprocess
import tempfile


def probe(hosts: list[str], timeout: int = 300) -> list[dict]:
    """Live-probe already-known hosts for status/title/tech — one request per host."""
    if not hosts:
        return []

    list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    try:
        list_file.write("\n".join(hosts))
        list_file.close()
        return _run(list_file.name, timeout)
    finally:
        os.unlink(list_file.name)


def _run(list_path: str, timeout: int) -> list[dict]:
    cmd = [
        "httpx",
        "-l", list_path,
        "-status-code", "-title", "-tech-detect",
        "-json", "-silent",
    ]
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
            "httpx not found — install with: "
            "go install github.com/projectdiscovery/httpx/cmd/httpx@latest"
        )
    except subprocess.TimeoutExpired:
        return []

    probed = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        host = data.get("input") or data.get("host")
        if not host:
            continue
        probed.append({
            "subdomain": host,
            "http_status": data.get("status_code"),
            "title": data.get("title"),
            "tech": data.get("tech") or [],
        })

    return probed
