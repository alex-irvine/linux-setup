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

mk_fakebin_cross_host_prompt() {
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
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/" && "$3" == "--dirs-only" ]]; then
  printf 'old-laptop/\nworkstation/\n'
  exit 0
fi
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/old-laptop" ]]; then
  printf 'hermes-20260701T010000Z.zip\n'
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

test_prompt_cross_host_restore() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_cross_host_prompt "$tmp"

  set +e
  output="$(printf '1\n' | PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "No backup found for current hostname path"
  assert_contains "$output" "Select backup source"
  assert_contains "$(cat "$TEST_LOG")" "hermes import called"
}

test_auto_same_host_restore
test_prompt_cross_host_restore
echo "PASS: restore-hermes contract tests"
