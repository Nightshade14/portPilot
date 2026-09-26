#!/usr/bin/env bash
# Starts the service on 127.0.0.1:5001, waits for /health, runs the contract
# cases, then stops the service. Exit code is the contract runner's.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-5001}"
BASE_URL="http://127.0.0.1:${PORT}"
PYTHON="${PYTHON:-python3}"

cd "$DIR"

"$PYTHON" app.py --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  if curl -sf "${BASE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if ! curl -sf "${BASE_URL}/health" >/dev/null 2>&1; then
  echo "service did not become healthy on ${BASE_URL}" >&2
  exit 1
fi

"$PYTHON" run_contract.py --base-url "$BASE_URL"
