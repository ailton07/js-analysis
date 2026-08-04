import requests
from rich.console import Console

console = Console()


def check_vpn() -> None:
    """Abort if traffic is not exiting through a Mullvad node."""
    try:
        data = requests.get("https://am.i.mullvad.net/json", timeout=10).json()
    except Exception as exc:
        raise SystemExit(f"VPN check failed — could not reach am.i.mullvad.net: {exc}")
    if not data.get("mullvad_exit_ip", False):
        ip = data.get("ip", "unknown")
        raise SystemExit(f"VPN check failed — exit IP {ip} is not a Mullvad node. Aborting.")
    ip = data.get("ip", "?")
    city = data.get("city", "?")
    country = data.get("country", "?")
    console.print(f"[green]VPN OK[/green]  {ip}  ({city}, {country})")
