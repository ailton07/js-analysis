#!/usr/bin/env bash
# Runs a one-off worker command and stops gluetun when done.
# Usage: bash scripts/run_worker.sh <worker-args>

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

docker compose run --rm worker "$@"
docker compose stop gluetun
