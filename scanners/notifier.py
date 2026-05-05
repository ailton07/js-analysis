import subprocess


def notify(finding: dict) -> None:
    try:
        subprocess.run(
            ["notify", "-silent"],
            input=_format(finding).encode(),
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def should_notify(finding: dict, config: dict) -> bool:
    cfg = config.get("scanners", {})
    min_entropy = cfg.get("min_entropy_notify", 3.5)
    high_value = {t.lower() for t in cfg.get("high_value_types", [])}

    if finding.get("entropy", 0) >= min_entropy:
        return True
    if finding.get("secret_type", "").lower() in high_value:
        return True
    return False


def _format(finding: dict) -> str:
    value = finding.get("value", "")
    preview = value[:80] + "..." if len(value) > 80 else value
    return (
        f"[{finding.get('detector', '?').upper()}] {finding.get('secret_type', 'unknown')}\n"
        f"URL:     {finding.get('url', 'unknown')}\n"
        f"Secret:  {preview}\n"
        f"Entropy: {finding.get('entropy', 0):.2f}"
    )
