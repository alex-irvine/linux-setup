#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/alarm/alarm-trigger"

assert_equals() {
  local expected="$1"
  local actual="$2"
  if [[ "$expected" != "$actual" ]]; then
    printf 'ASSERT FAILED: expected "%s", got "%s"\n' "$expected" "$actual"
    return 1
  fi
}

test_notification_runs_before_sound() {
  local tmp fakebin home data_dir order_file
  tmp="$(mktemp -d)"
  fakebin="$tmp/fakebin"
  home="$tmp/home"
  data_dir="$home/.local/share/alarm-cli"
  order_file="$tmp/order.log"

  mkdir -p "$fakebin" "$home"

  cat >"$fakebin/notify-send" <<EOF
#!/usr/bin/env bash
echo notify >>"$order_file"
exit 0
EOF

  cat >"$fakebin/paplay" <<EOF
#!/usr/bin/env bash
echo sound >>"$order_file"
exit 0
EOF

  chmod +x "$fakebin/notify-send" "$fakebin/paplay"

  HOME="$home" PATH="$fakebin:$PATH" ALARM_DATA_DIR="$data_dir" bash "$SUT" 1 "2030-01-01 07:30" "Order"

  local first second
  first="$(sed -n '1p' "$order_file")"
  second="$(sed -n '2p' "$order_file")"

  assert_equals "notify" "$first"
  assert_equals "sound" "$second"

  rm -rf "$tmp"
}

test_notification_runs_before_sound
printf 'PASS: alarm-trigger contract tests\n'
