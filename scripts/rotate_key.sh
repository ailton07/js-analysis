#!/usr/bin/env bash
# Generates a new WireGuard key pair, registers the public key with Mullvad,
# and updates MULLVAD_WG_KEY and MULLVAD_WG_ADDR in .env.
#
# Requirements: wg (wireguard-tools), curl, jq
# Usage: bash scripts/rotate_key.sh

set -euo pipefail

ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE" >&2
  exit 1
fi

for bin in wg curl jq; do
  if ! command -v "$bin" &>/dev/null; then
    echo "ERROR: $bin is required but not installed" >&2
    exit 1
  fi
done

ACCOUNT=$(grep -E '^MULLVAD_ACCOUNT=' "$ENV_FILE" | cut -d= -f2 | tr -d '[:space:]')
if [[ -z "$ACCOUNT" || "$ACCOUNT" == "0000000000000000" ]]; then
  echo "ERROR: Set MULLVAD_ACCOUNT in .env first" >&2
  exit 1
fi

echo "Generating WireGuard key pair..."
PRIVATE_KEY=$(wg genkey)
PUBLIC_KEY=$(echo "$PRIVATE_KEY" | wg pubkey)

echo "Registering public key with Mullvad..."
RESPONSE=$(curl -sf -X POST "https://api.mullvad.net/app/v1/wireguard-keys" \
  -H "Authorization: Token $ACCOUNT" \
  -H "Content-Type: application/json" \
  -d "{\"pubkey\": \"$PUBLIC_KEY\"}")

IPV4=$(echo "$RESPONSE" | jq -r '.ipv4_address')

if [[ -z "$IPV4" || "$IPV4" == "null" ]]; then
  echo "ERROR: Failed to register key. Mullvad response:" >&2
  echo "$RESPONSE" >&2
  exit 1
fi

echo "Assigned address: $IPV4"

# Update .env in place
sed -i.bak \
  -e "s|^MULLVAD_WG_KEY=.*|MULLVAD_WG_KEY=$PRIVATE_KEY|" \
  -e "s|^MULLVAD_WG_ADDR=.*|MULLVAD_WG_ADDR=$IPV4|" \
  "$ENV_FILE"

rm -f "$ENV_FILE.bak"

echo ""
echo "Done. Restart gluetun to apply:"
echo "  docker compose restart gluetun"
