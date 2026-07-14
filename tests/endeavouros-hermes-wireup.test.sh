#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *'bash "$SCRIPT_DIR/hermes-setup.sh"'* ]] || {
  echo "FAIL: missing hermes-setup.sh invocation"
  exit 1
}

[[ "$CONTENT" == *'stow --no-folding --target="$HOME" --restow hermes'* ]] || {
  echo "FAIL: missing non-folding final hermes restow"
  exit 1
}

[[ "$CONTENT" == *'echo "==== Restowing Hermes dotfiles (config, scripts, skills) ===="'* ]] || {
  echo "FAIL: Hermes restow does not document skills coverage"
  exit 1
}

[[ "$CONTENT" == *'~/Proj/linux-setup/restore-hermes.sh'* ]] || {
  echo "FAIL: missing setup-owned restore command helper text"
  exit 1
}

[[ "$CONTENT" != *'~/.hermes/scripts/restore-hermes.sh'* ]] || {
  echo "FAIL: still references old stow-owned restore command in helper text"
  exit 1
}

if printf '%s\n' "$CONTENT" | grep -Eq 'stow --target="\$HOME" --restow .* hermes '; then
  echo "FAIL: hermes still included in initial broad stow list"
  exit 1
fi

echo "PASS: endeavouros hermes wireup present"
