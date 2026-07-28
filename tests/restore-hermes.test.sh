#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/restore-hermes.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output NOT to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

mk_fakebin_auto_same_host() {
  local fakebin="$1"
  cat >"$fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
echo "hermes import called: $*" >>"$TEST_LOG"
exit 0
EOF

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"enable --now hermes-backup.timer"* ]]; then
  echo "systemctl enable hermes-backup.timer called: $*" >>"$TEST_LOG"
fi
exit 0
EOF

  cat >"$fakebin/rclone" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/test-host" ]]; then
  printf 'hermes-20260710T010000Z.zip\nhermes-20260711T010000Z.zip\n'
  exit 0
fi
if [[ "$1" == "copyto" ]]; then
  echo "rclone copyto called: $*" >>"$TEST_LOG"
  dst="$4"
  mkdir -p "$(dirname "$dst")"
  : >"$dst"
  exit 0
fi
if [[ "$1" == "listremotes" ]]; then
  echo "gdrive:"
  exit 0
fi
exit 0
EOF

  chmod +x "$fakebin/hermes" "$fakebin/systemctl" "$fakebin/rclone"
}

test_auto_same_host_restore() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_auto_same_host "$tmp"

  set +e
  output="$(PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "Selected archive: gdrive:hermes-backups/test-host/hermes-20260711T010000Z.zip"
  assert_contains "$(cat "$TEST_LOG")" "hermes import called"
  assert_contains "$(cat "$TEST_LOG")" "systemctl enable hermes-backup.timer called"
}

mk_fakebin_cross_host_auto_select() {
  local fakebin="$1"
  cat >"$fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
echo "hermes import called: $*" >>"$TEST_LOG"
exit 0
EOF

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"enable --now hermes-backup.timer"* ]]; then
  echo "systemctl enable hermes-backup.timer called: $*" >>"$TEST_LOG"
fi
exit 0
EOF

  cat >"$fakebin/rclone" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/test-host" ]]; then
  exit 0
fi
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/" && "$3" == "-R" ]]; then
  printf 'aaa-newhost/hermes-20260720T030000Z.zip\nzzz-oldhost/hermes-20260701T030000Z.zip\n'
  exit 0
fi
if [[ "$1" == "copyto" ]]; then
  echo "rclone copyto called: $*" >>"$TEST_LOG"
  dst="$4"
  mkdir -p "$(dirname "$dst")"
  : >"$dst"
  exit 0
fi
if [[ "$1" == "listremotes" ]]; then
  echo "gdrive:"
  exit 0
fi
exit 0
EOF

  chmod +x "$fakebin/hermes" "$fakebin/systemctl" "$fakebin/rclone"
}

test_cross_host_auto_selects_most_recent_regardless_of_hostname() {
  local tmp output rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_cross_host_auto_select "$tmp"

  set +e
  output="$(PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "auto-selected most recent cross-host backup: gdrive:hermes-backups/aaa-newhost/hermes-20260720T030000Z.zip"
  assert_contains "$(cat "$TEST_LOG")" "rclone copyto called: copyto gdrive:hermes-backups/aaa-newhost/hermes-20260720T030000Z.zip"
  assert_contains "$(cat "$TEST_LOG")" "hermes import called"
}

mk_fakebin_for_gateway_tests() {
  local fakebin="$1"
  cat >"$fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
echo "hermes called: $*" >>"$TEST_LOG"
exit 0
EOF

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

  cat >"$fakebin/rclone" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/test-host" ]]; then
  printf 'hermes-20260711T010000Z.zip\n'
  exit 0
fi
if [[ "$1" == "copyto" ]]; then
  dst="$4"
  mkdir -p "$(dirname "$dst")"
  : >"$dst"
  exit 0
fi
if [[ "$1" == "listremotes" ]]; then
  echo "gdrive:"
  exit 0
fi
exit 0
EOF

  chmod +x "$fakebin/hermes" "$fakebin/systemctl" "$fakebin/rclone"
}

test_root_gateway_installed_when_messaging_token_present() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_for_gateway_tests "$tmp"
  mkdir -p "$tmp/home/.hermes"
  printf 'TELEGRAM_BOT_TOKEN=123456:abcdefghijklmnopqrstuvwxyz0123456789\n' >"$tmp/home/.hermes/.env"

  PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes >/dev/null 2>&1

  assert_contains "$(cat "$TEST_LOG")" "hermes called: gateway install"
}

test_root_gateway_skipped_when_no_messaging_token() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_for_gateway_tests "$tmp"
  mkdir -p "$tmp/home/.hermes"
  printf 'SOME_OTHER_VAR=value\n' >"$tmp/home/.hermes/.env"

  PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes >/dev/null 2>&1

  assert_not_contains "$(cat "$TEST_LOG")" "gateway install"
}

test_cross_host_auto_selects_most_recent_regardless_of_hostname
test_root_gateway_installed_when_messaging_token_present
test_root_gateway_skipped_when_no_messaging_token
test_auto_same_host_restore
# test_prompt_cross_host_restore (the old --yes + interactive-host-picker
# scenario) was retired here: under the new resolve_cross_host_remote(),
# --yes now means "auto-select, never prompt" (see
# test_cross_host_auto_selects_most_recent_regardless_of_hostname above) —
# that IS the fix for the hang risk this change addresses, not a
# regression. The genuinely-interactive (no --yes, real tty) path is
# verified manually per the implementation plan's Final Verification Gate,
# since a real controlling terminal can't be faked like a PATH binary.
echo "PASS: restore-hermes contract tests"
