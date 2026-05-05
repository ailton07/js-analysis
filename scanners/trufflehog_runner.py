import json
import math
import subprocess
from pathlib import Path


def scan(source_dir: Path, target_id: int, url_map: dict) -> list[dict]:
    try:
        result = subprocess.run(
            [
                "trufflehog", "filesystem",
                str(source_dir),
                "--json",
                "--no-update",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "trufflehog not found — install with: "
            "go install github.com/trufflesecurity/trufflehog/v3@latest"
        )

    findings = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        file_path = (
            data.get("SourceMetadata", {})
            .get("Data", {})
            .get("Filesystem", {})
            .get("file", "")
        )
        file_hash = Path(file_path).stem if file_path else ""
        raw_value = (data.get("Raw") or data.get("RawV2") or "")[:500]

        findings.append({
            "target_id": target_id,
            "file_hash": file_hash,
            "url": url_map.get(file_hash, ""),
            "detector": "trufflehog",
            "secret_type": data.get("DetectorName", ""),
            "value": raw_value,
            "entropy": _entropy(raw_value),
            "line": 0,
        })

    return findings


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in freq.values())
