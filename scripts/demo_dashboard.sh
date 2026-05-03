#!/usr/bin/env bash
set -euo pipefail

HOST_NAME="${HOST_NAME:-127.0.0.1}"
PORT="${PORT:-8010}"
API_KEY="${PRIVATELABBENCH_DASHBOARD_API_KEY:-dashboard-secret}"
ORGANIZATION_ID="${ORGANIZATION_ID:-demo-customer}"
CONFIG_PATH="${CONFIG_PATH:-configs/prediction_eval.yaml}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export PRIVATELABBENCH_DASHBOARD_API_KEY="$API_KEY"

BASE_URL="http://${HOST_NAME}:${PORT}"
DASHBOARD_URL="${BASE_URL}/?api_key=${API_KEY}"

dashboard_ready() {
  python - "$BASE_URL" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

base_url = sys.argv[1]
with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
}

if ! dashboard_ready; then
  echo "Starting PrivateLabBench dashboard on $BASE_URL ..."
  mkdir -p .privatelabbench_dashboard
  nohup python -m privatelabbench.cli serve-dashboard \
    --host "$HOST_NAME" \
    --port "$PORT" \
    > .privatelabbench_dashboard/dashboard.log 2>&1 &

  ready=0
  for _ in $(seq 1 30); do
    sleep 1
    if dashboard_ready; then
      ready=1
      break
    fi
  done
  if [ "$ready" -ne 1 ]; then
    echo "Dashboard did not become ready at $BASE_URL" >&2
    echo "Log: .privatelabbench_dashboard/dashboard.log" >&2
    exit 1
  fi
else
  echo "Dashboard is already running on $BASE_URL."
fi

echo "Syncing sanitized demo run from $CONFIG_PATH ..."
python -m privatelabbench.cli sync-dashboard "$CONFIG_PATH" \
  --endpoint "$BASE_URL" \
  --api-key "$API_KEY" \
  --organization-id "$ORGANIZATION_ID"

echo
echo "Dashboard demo is ready:"
echo "$DASHBOARD_URL"
echo
echo "Local reports are under: $REPO_ROOT/reports"
