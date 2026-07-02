#!/bin/bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[tailscale] missing required command: $cmd"
    return 1
  fi
}

main() {
  require_cmd tailscale || exit 1
  require_cmd systemctl || exit 1
  echo "[tailscale] prerequisites OK"
}

main "$@"
