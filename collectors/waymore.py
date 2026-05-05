import re
import subprocess
from pathlib import Path

_JS_RE = re.compile(r'\.js(\?|$)', re.IGNORECASE)


def collect(domain: str, output_dir: Path, timeout: int = 600) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"waymore_{domain}.txt"

    try:
        subprocess.run(
            ["waymore", "-i", domain, "-mode", "U", "-oU", str(output_file)],
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
