import json
import os
import subprocess
import tempfile


def resolve(hosts: list[str], timeout: int = 900) -> list[dict]:
    """Resolve hosts to IPs via dnsx, dropping unresolved and wildcard-flagged entries.

    Default bumped from 300s to match passive.collect — a large multi-apex
    scope means more hosts here too, and dnsx needs the same headroom.
    """
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
    # -wd (manual wildcard-domain) is broken in dnsx 1.2.3: it drops every
    # result, including verified non-wildcard resolutions. -auto-wildcard
    # detects wildcards per-domain from the input itself and works correctly.
    cmd = [
        "dnsx",
        "-l", list_path,
        "-a", "-resp",
        "-auto-wildcard",
        "-json",
        "-silent",
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
            "dnsx not found — install with: "
            "go install github.com/projectdiscovery/dnsx/cmd/dnsx@latest"
        )
    except subprocess.TimeoutExpired:
        return []

    resolved = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        host = data.get("host")
        if not host:
            continue
        ips = data.get("a") or []
        resolved.append({"subdomain": host, "resolved_ip": ips[0] if ips else None})

    return resolved
