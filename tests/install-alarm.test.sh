#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/alarm/install-alarm.sh"

test_install_alarm_places_files_and_data() {
  local tmp home_dir bin_dir data_dir
  tmp="$(mktemp -d)"
  home_dir="$tmp/home"
  bin_dir="$home_dir/.local/bin"
  data_dir="$home_dir/.local/share/alarm-cli"
  mkdir -p "$home_dir"

  HOME="$home_dir" \
  ALARM_BIN_DIR="$bin_dir" \
  ALARM_DATA_DIR="$data_dir" \
  ALARM_SKIP_DEP_INSTALL=1 \
  ALARM_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  [[ -x "$bin_dir/alarm" ]]
  [[ -x "$bin_dir/alarm-trigger" ]]
  [[ -f "$data_dir/alarms.tsv" ]]
  [[ -f "$data_dir/alarm.log" ]]

  rm -rf "$tmp"
}

test_install_alarm_places_files_and_data
printf 'PASS: install-alarm contract tests\n'
