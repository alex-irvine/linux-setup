#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$(cat "$ROOT_DIR/README.md")"

[[ "$CONTENT" == *"## Production error tickets"* ]] || {
  echo "FAIL: README missing Production error tickets section"
  exit 1
}

[[ "$CONTENT" == *"ERROR_TICKETS_MODE"* ]] || {
  echo "FAIL: README missing the dry-run/live switch"
  exit 1
}

[[ "$CONTENT" == *"journalctl --user -u production-error-tickets"* ]] || {
  echo "FAIL: README missing the log command"
  exit 1
}

echo "PASS: production-error-tickets docs contract checks"
