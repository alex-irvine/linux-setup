#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README_FILE="$ROOT_DIR/README.md"
CONTENT="$(cat "$README_FILE")"

[[ "$CONTENT" == *"## Alarm CLI"* ]] || {
  echo "FAIL: README missing Alarm CLI section"
  exit 1
}

[[ "$CONTENT" == *"alarm add \"2026-07-03 07:30\" \"Gym\""* ]] || {
  echo "FAIL: README missing alarm add absolute example"
  exit 1
}

[[ "$CONTENT" == *"alarm add --in 45m \"Tea\""* ]] || {
  echo "FAIL: README missing alarm add relative example"
  exit 1
}

[[ "$CONTENT" == *"alarm list"* ]] || {
  echo "FAIL: README missing alarm list example"
  exit 1
}

[[ "$CONTENT" == *"alarm delete <alarm-id>"* ]] || {
  echo "FAIL: README missing alarm delete example"
  exit 1
}

echo "PASS: alarm docs contract checks"
