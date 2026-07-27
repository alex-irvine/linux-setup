#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README_FILE="$ROOT_DIR/README.md"
CONTENT="$(cat "$README_FILE")"

[[ "$CONTENT" == *"## Automation watchdog"* ]] || {
  echo "FAIL: README missing Automation watchdog section"
  exit 1
}

[[ "$CONTENT" == *"automation-watchdog --dry-run"* ]] || {
  echo "FAIL: README missing automation-watchdog --dry-run example"
  exit 1
}

[[ "$CONTENT" == *"~/.local/share/automation-watchdog/watchdog.log"* ]] || {
  echo "FAIL: README missing watchdog.log path"
  exit 1
}

echo "PASS: automation-watchdog docs contract checks"
