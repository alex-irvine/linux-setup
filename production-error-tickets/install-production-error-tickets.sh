#!/usr/bin/env bash
set -euo pipefail

# Installs the daily production-error ticket timer. The service runs the
# ticketing-production-errors skill (dotfiles) through `claude -p`; its
# Condition* lines skip the run until the Claude CLI and the triage state
# directory exist, so installing before they do is safe.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="${ERROR_TICKETS_UNIT_DIR:-$HOME/.config/systemd/user}"

install_files() {
  mkdir -p "$UNIT_DIR"

  install -m 644 "$SCRIPT_DIR/production-error-tickets.service" "$UNIT_DIR/production-error-tickets.service"
  install -m 644 "$SCRIPT_DIR/production-error-tickets.timer" "$UNIT_DIR/production-error-tickets.timer"
}

enable_timer() {
  if [[ "${ERROR_TICKETS_SKIP_SYSTEMD:-0}" == "1" ]]; then
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable --now production-error-tickets.timer
  fi
}

main() {
  install_files
  enable_timer

  printf '[production-error-tickets] installed units to %s\n' "$UNIT_DIR"
}

main "$@"
