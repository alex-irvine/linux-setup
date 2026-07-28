#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -f "$ROOT_DIR/NEW-LAPTOP.md" ]] || {
  echo "FAIL: NEW-LAPTOP.md missing"
  exit 1
}

CONTENT="$(cat "$ROOT_DIR/NEW-LAPTOP.md")"

[[ "$CONTENT" == *"rclone config"* ]] || {
  echo "FAIL: NEW-LAPTOP.md missing rclone config step"
  exit 1
}

[[ "$CONTENT" == *"rclone authorize"* ]] || {
  echo "FAIL: NEW-LAPTOP.md missing headless/no-browser fallback"
  exit 1
}

[[ "$CONTENT" == *"by design"* ]] || {
  echo "FAIL: NEW-LAPTOP.md missing config.yaml/SOUL.md by-design note"
  exit 1
}

README_CONTENT="$(cat "$ROOT_DIR/README.md")"

[[ "$README_CONTENT" == *"[NEW-LAPTOP.md](NEW-LAPTOP.md)"* ]] || {
  echo "FAIL: README missing link to NEW-LAPTOP.md"
  exit 1
}

echo "PASS: new-laptop docs contract checks"
