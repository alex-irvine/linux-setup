#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${WATCHDOG_BIN_DIR:-$HOME/.local/bin}"
DATA_DIR="${WATCHDOG_DATA_DIR:-$HOME/.local/share/automation-watchdog}"
UNIT_DIR="${WATCHDOG_UNIT_DIR:-$HOME/.config/systemd/user}"

install_files() {
  mkdir -p "$BIN_DIR"
  mkdir -p "$DATA_DIR"
  mkdir -p "$UNIT_DIR"

  install -m 755 "$SCRIPT_DIR/automation-watchdog" "$BIN_DIR/automation-watchdog"
  install -m 644 "$SCRIPT_DIR/automation-watchdog.timer" "$UNIT_DIR/automation-watchdog.timer"
  install -m 644 "$SCRIPT_DIR/automation-watchdog.service" "$UNIT_DIR/automation-watchdog.service"

  touch "$DATA_DIR/watchdog.log"
}

enable_timer() {
  if [[ "${WATCHDOG_SKIP_SYSTEMD:-0}" == "1" ]]; then
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable --now automation-watchdog.timer
  fi
}

main() {
  install_files
  enable_timer

  printf '[automation-watchdog] installed to %s/automation-watchdog\n' "$BIN_DIR"
}

main "$@"
