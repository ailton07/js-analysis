import csv
import subprocess
from pathlib import Path


def scan(
    source_dir: Path,
    target_id: int,
    url_map: dict,
    report_path: Path,
) -> list[dict]:
    report_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                "gitleaks", "detect",
                "--source", str(source_dir),
                "--report-format", "csv",
                "--report-path", str(report_path),
                "--no-git",
                "--exit-code", "0",
            ],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "gitleaks not found — install with: "
            "go install github.com/gitleaks/gitleaks/v8@latest"
        )

    if not report_path.exists():
        return []

    findings = []
    with open(report_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            file_hash = Path(row.get("File", "")).stem
            findings.append({
                "target_id": target_id,
                "file_hash": file_hash,
                "url": url_map.get(file_hash, ""),
                "detector": "gitleaks",
                "secret_type": row.get("RuleID", ""),
                "value": row.get("Secret", ""),
                "entropy": float(row.get("Entropy") or 0),
                "line": int(row.get("StartLine") or 0),
            })

    return findings
