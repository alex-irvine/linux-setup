#!/usr/bin/env bash
set -euo pipefail

FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *"automation-watchdog/install-automation-watchdog.sh"* ]] || {
  echo "FAIL: automation-watchdog installer call missing"
  exit 1
}

[[ "$CONTENT" == *"list-timers automation-watchdog.timer"* ]] || {
  echo "FAIL: automation-watchdog timer diagnostic call missing"
  exit 1
}

echo "PASS: automation-watchdog wireup present"
