import subprocess


def collect(domain: str, timeout: int = 300) -> list[str]:
    try:
        result = subprocess.run(
            ["subfinder", "-d", domain, "-silent"],
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
