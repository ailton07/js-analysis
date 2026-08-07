import os
import subprocess
import tempfile


def collect(domain: str, timeout: int = 300, scope: list[str] | None = None) -> list[str]:
    # subfinder -d only queries the single primary domain. Multi-domain scope
    # entries in target yaml files need -dL (domain list file) so every
    # in-scope domain gets enumerated, not just the primary one.
    domains = scope or [domain]
    if len(domains) > 1:
        list_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        try:
            list_file.write("\n".join(domains))
            list_file.close()
            cmd = ["subfinder", "-dL", list_file.name, "-silent"]
            return _run(cmd, timeout)
        finally:
            os.unlink(list_file.name)
    return _run(["subfinder", "-d", domain, "-silent"], timeout)


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
