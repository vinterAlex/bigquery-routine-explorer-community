#!/usr/bin/env bash
# Setup script for BigQuery Routine Explorer (Community Edition) secrets.
#
# Usage:
#   ./setup_secrets.sh                          # create secrets/ folder only
#   ./setup_secrets.sh /path/to/key.json        # copy + validate a service-account key
#
# Creates the `secrets` folder (mounted read-only into the Docker container at
# /secrets) and, if given a key, installs it as secrets/key.json, the default
# path the app reads (override with SA_KEY_PATH).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$ROOT/secrets"
KEY_TARGET="$SECRETS_DIR/key.json"
KEY_PATH="${1:-}"

echo ""
echo "BigQuery Routine Explorer — COMMUNITY EDITION"
echo "----------------------------------------------"
echo ""

mkdir -p "$SECRETS_DIR"
echo "Using secrets directory: $SECRETS_DIR"

if [[ -n "$KEY_PATH" ]]; then
  if [[ -f "$KEY_PATH" ]]; then
    cp "$KEY_PATH" "$KEY_TARGET"
    echo "Copied key to $KEY_TARGET"
  else
    echo "ERROR: key not found at '$KEY_PATH'" >&2
    exit 1
  fi
fi

if [[ -f "$KEY_TARGET" ]]; then
  if python3 - "$KEY_TARGET" <<'PY'
import json, sys
try:
    k = json.load(open(sys.argv[1]))
    ok = k.get("type") == "service_account" and "client_email" in k and "private_key" in k
    if ok:
        print(f"OK: valid service-account key ({k['client_email']})")
    else:
        print("WARNING: does not look like a GCP service-account key JSON.")
        sys.exit(1)
except Exception as e:
    print(f"WARNING: not valid JSON: {e}")
    sys.exit(1)
PY
  then
    :
  else
    echo "Validation failed - exiting." >&2
    exit 1
  fi
else
  echo "No service-account key found yet."
  echo "Put your read-only BigQuery service-account JSON as secrets/key.json (or run: ./setup_secrets.sh /path/to/key.json)"
  echo "Required IAM roles on each project: roles/bigquery.metadataViewer + roles/bigquery.jobUser"
fi