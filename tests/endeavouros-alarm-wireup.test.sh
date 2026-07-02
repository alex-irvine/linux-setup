#!/usr/bin/env bash
set -euo pipefail

FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *"alarm/install-alarm.sh"* ]] || {
  echo "FAIL: alarm installer call missing"
  exit 1
}

echo "PASS: alarm wireup present"
