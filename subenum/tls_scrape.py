import json
import os
import subprocess
import tempfile


def scrape(hosts: list[str], timeout: int = 300) -> list[str]:
    """Scrape TLS certificate SANs/CNs from already-known hosts — one request per host."""
    if not hosts:
        return []

    list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    try:
        list_file.write("\n".join(hosts))
        list_file.close()
        return _run(list_file.name, timeout)
    finally:
        os.unlink(list_file.name)


def _run(list_path: str, timeout: int) -> list[str]:
    cmd = ["tlsx", "-l", list_path, "-san", "-cn", "-silent", "-json"]
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
            "tlsx not found — install with: "
            "go install github.com/projectdiscovery/tlsx/cmd/tlsx@latest"
        )
    except subprocess.TimeoutExpired:
        return []

    names: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidates = [data.get("subject_cn"), *(data.get("subject_an") or [])]
        for name in candidates:
            if name and not name.startswith("*."):
                names.add(name)

    return sorted(names)
