#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README_FILE="$ROOT_DIR/README.md"
CONTENT="$(cat "$README_FILE")"

[[ "$CONTENT" == *"Runs hermes-setup.sh"* ]] || {
  echo "FAIL: README missing hermes-setup.sh mention"
  exit 1
}

[[ "$CONTENT" == *"~/Proj/linux-setup/restore-hermes.sh"* ]] || {
  echo "FAIL: README missing setup-owned restore command"
  exit 1
}

[[ "$CONTENT" != *"~/.hermes/scripts/restore-hermes.sh"* ]] || {
  echo "FAIL: README still references old stow-owned restore command"
  exit 1
}

[[ "$CONTENT" == *"same-host"* ]] || {
  echo "FAIL: README missing same-host auto-restore policy"
  exit 1
}

echo "PASS: hermes/firecrawl docs contract checks"
