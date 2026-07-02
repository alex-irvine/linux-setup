#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${ALARM_BIN_DIR:-$HOME/.local/bin}"
DATA_DIR="${ALARM_DATA_DIR:-$HOME/.local/share/alarm-cli}"

install_files() {
  mkdir -p "$BIN_DIR"
  mkdir -p "$DATA_DIR"

  install -m 755 "$SCRIPT_DIR/alarm" "$BIN_DIR/alarm"
  install -m 755 "$SCRIPT_DIR/alarm-trigger" "$BIN_DIR/alarm-trigger"

  touch "$DATA_DIR/alarms.tsv"
  touch "$DATA_DIR/alarm.log"
}

install_dependencies() {
  if [[ "${ALARM_SKIP_DEP_INSTALL:-0}" == "1" ]]; then
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm --needed at libnotify libcanberra
  fi
}

ensure_atd_running() {
  if [[ "${ALARM_SKIP_SYSTEMD:-0}" == "1" ]]; then
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable --now atd
  fi
}

main() {
  install_dependencies
  ensure_atd_running
  install_files

  printf '[alarm] installed to %s/alarm\n' "$BIN_DIR"
}

main "$@"
