#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *'stow --no-folding --target="$HOME" --restow codex'* ]] || {
  echo "FAIL: missing no-folding stow of the dotfiles codex package"
  exit 1
}

[[ "$CONTENT" == *'bash "$SCRIPT_DIR/codex-setup.sh"'* ]] || {
  echo "FAIL: missing codex-setup.sh call"
  exit 1
}

stow_line="$(grep -n 'restow codex' "$FILE" | cut -d: -f1)"
setup_line="$(grep -n 'codex-setup.sh"' "$FILE" | cut -d: -f1)"
(( stow_line < setup_line )) || {
  echo "FAIL: codex-setup.sh must run after the codex package is stowed"
  exit 1
}

echo "PASS: endeavouros codex wireup present"
