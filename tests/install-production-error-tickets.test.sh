#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/production-error-tickets/install-production-error-tickets.sh"

test_install_places_units() {
  local tmp unit_dir
  tmp="$(mktemp -d)"
  unit_dir="$tmp/home/.config/systemd/user"

  HOME="$tmp/home" \
  ERROR_TICKETS_UNIT_DIR="$unit_dir" \
  ERROR_TICKETS_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  [[ -f "$unit_dir/production-error-tickets.service" ]]
  [[ -f "$unit_dir/production-error-tickets.timer" ]]
  grep -q 'claude -p "/ticketing-production-errors"' "$unit_dir/production-error-tickets.service"
  grep -q 'OnCalendar=\*-\*-\* 08:45:00 UTC' "$unit_dir/production-error-tickets.timer"
  grep -q 'Persistent=true' "$unit_dir/production-error-tickets.timer"

  rm -rf "$tmp"
}

test_install_is_idempotent_on_rerun() {
  local tmp unit_dir
  tmp="$(mktemp -d)"
  unit_dir="$tmp/home/.config/systemd/user"

  for _ in 1 2; do
    HOME="$tmp/home" \
    ERROR_TICKETS_UNIT_DIR="$unit_dir" \
    ERROR_TICKETS_SKIP_SYSTEMD=1 \
    bash "$INSTALLER" >/dev/null
  done

  cmp -s "$ROOT_DIR/production-error-tickets/production-error-tickets.timer" "$unit_dir/production-error-tickets.timer"

  rm -rf "$tmp"
}

test_install_places_units
test_install_is_idempotent_on_rerun

echo "PASS: production-error-tickets installer"
