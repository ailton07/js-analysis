#!/bin/sh
set -e

echo "[*] Verifying VPN connection..."

VPN_DATA=$(wget -qO- --timeout=10 https://am.i.mullvad.net/json 2>/dev/null) || {
    echo "[!] VPN check failed — could not reach am.i.mullvad.net. Aborting."
    exit 1
}

IS_MULLVAD=$(echo "$VPN_DATA" | grep -o '"mullvad_exit_ip":true')
if [ -z "$IS_MULLVAD" ]; then
    IP=$(echo "$VPN_DATA" | grep -o '"ip":"[^"]*"' | cut -d'"' -f4)
    echo "[!] VPN check failed — exit IP ${IP} is not a Mullvad node. Aborting."
    exit 1
fi

IP=$(echo "$VPN_DATA"      | grep -o '"ip":"[^"]*"'      | cut -d'"' -f4)
CITY=$(echo "$VPN_DATA"    | grep -o '"city":"[^"]*"'    | cut -d'"' -f4)
COUNTRY=$(echo "$VPN_DATA" | grep -o '"country":"[^"]*"' | cut -d'"' -f4)

echo "[+] VPN OK  ${IP}  (${CITY}, ${COUNTRY})"

exec nuclei "$@"
