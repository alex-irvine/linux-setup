#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$(cat "$ROOT_DIR/endeavouros-setup.sh")"

[[ "$CONTENT" == *"production-error-tickets/install-production-error-tickets.sh"* ]] || {
  echo "FAIL: production-error-tickets installer call missing"
  exit 1
}

[[ "$CONTENT" == *"list-timers production-error-tickets.timer"* ]] || {
  echo "FAIL: production-error-tickets timer diagnostic call missing"
  exit 1
}

WATCHDOG="$(cat "$ROOT_DIR/automation-watchdog/automation-watchdog")"
[[ "$WATCHDOG" == *"TRACKED_TIMERS=("*"production-error-tickets"*")"* ]] || {
  echo "FAIL: automation-watchdog does not track production-error-tickets.timer"
  exit 1
}

echo "PASS: production-error-tickets wireup present"
