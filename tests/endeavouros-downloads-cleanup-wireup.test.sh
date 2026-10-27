#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *'systemctl --user enable --now downloads-cleanup.timer'* ]] || {
  echo "FAIL: missing downloads-cleanup.timer enable"
  exit 1
}

[[ "$CONTENT" == *'echo "==== Downloads cleanup timer ===="'* ]] || {
  echo "FAIL: missing Downloads cleanup section marker"
  exit 1
}

# The units come from the dotfiles systemd package, which must be stowed first.
stow_line="$(grep -n 'restow agents .* systemd ' "$FILE" | head -1 | cut -d: -f1)"
enable_line="$(grep -n 'enable --now downloads-cleanup.timer' "$FILE" | cut -d: -f1)"
[[ -n "$stow_line" ]] && (( stow_line < enable_line )) || {
  echo "FAIL: downloads-cleanup.timer must be enabled after the systemd package is stowed"
  exit 1
}

echo "PASS: endeavouros downloads-cleanup wireup present"
