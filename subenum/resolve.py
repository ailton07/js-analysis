import json
import os
import subprocess
import tempfile


def resolve(hosts: list[str], domain: str, timeout: int = 300) -> list[dict]:
    """Resolve hosts to IPs via dnsx, dropping unresolved and wildcard-flagged entries."""
    if not hosts:
        return []

    list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    try:
        list_file.write("\n".join(hosts))
        list_file.close()
        return _run(list_file.name, domain, timeout)
    finally:
        os.unlink(list_file.name)


def _run(list_path: str, domain: str, timeout: int) -> list[dict]:
    cmd = [
        "dnsx",
        "-l", list_path,
        "-a", "-resp",
        "-wd", domain,
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
