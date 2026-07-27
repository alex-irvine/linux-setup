#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/automation-watchdog/install-automation-watchdog.sh"

test_install_places_files_and_data() {
  local tmp home_dir bin_dir data_dir unit_dir
  tmp="$(mktemp -d)"
  home_dir="$tmp/home"
  bin_dir="$home_dir/.local/bin"
  data_dir="$home_dir/.local/share/automation-watchdog"
  unit_dir="$home_dir/.config/systemd/user"
  mkdir -p "$home_dir"

  HOME="$home_dir" \
  WATCHDOG_BIN_DIR="$bin_dir" \
  WATCHDOG_DATA_DIR="$data_dir" \
  WATCHDOG_UNIT_DIR="$unit_dir" \
  WATCHDOG_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  [[ -x "$bin_dir/automation-watchdog" ]]
  [[ -f "$unit_dir/automation-watchdog.timer" ]]
  [[ -f "$unit_dir/automation-watchdog.service" ]]
  [[ -f "$data_dir/watchdog.log" ]]

  rm -rf "$tmp"
}

test_install_is_idempotent_on_rerun() {
  local tmp home_dir bin_dir data_dir unit_dir
  tmp="$(mktemp -d)"
  home_dir="$tmp/home"
  bin_dir="$home_dir/.local/bin"
  data_dir="$home_dir/.local/share/automation-watchdog"
  unit_dir="$home_dir/.config/systemd/user"
  mkdir -p "$home_dir"

  HOME="$home_dir" \
  WATCHDOG_BIN_DIR="$bin_dir" \
  WATCHDOG_DATA_DIR="$data_dir" \
  WATCHDOG_UNIT_DIR="$unit_dir" \
  WATCHDOG_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  echo "existing watchdog.log content" >>"$data_dir/watchdog.log"

  HOME="$home_dir" \
  WATCHDOG_BIN_DIR="$bin_dir" \
  WATCHDOG_DATA_DIR="$data_dir" \
  WATCHDOG_UNIT_DIR="$unit_dir" \
  WATCHDOG_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  [[ -x "$bin_dir/automation-watchdog" ]]
  [[ -f "$unit_dir/automation-watchdog.timer" ]]
  [[ -f "$unit_dir/automation-watchdog.service" ]]
  grep -q "existing watchdog.log content" "$data_dir/watchdog.log"

  rm -rf "$tmp"
}

test_install_places_files_and_data
test_install_is_idempotent_on_rerun
printf 'PASS: install-automation-watchdog contract tests\n'
