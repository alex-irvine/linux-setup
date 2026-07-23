#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *'systemctl --user enable --now open-design.service'* ]] || {
  echo "FAIL: missing open-design.service enable"
  exit 1
}

[[ "$CONTENT" == *'echo "==== Open Design daemon ===="'* ]] || {
  echo "FAIL: missing Open Design daemon section marker"
  exit 1
}

echo "PASS: endeavouros open-design wireup present"
