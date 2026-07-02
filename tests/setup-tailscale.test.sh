#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/setup-tailscale.sh"

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
    printf 'ASSERT FAILED: expected output to not contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

install_fake_bash() {
  local fakebin="$1"
  local real_bash
  local real_head
  real_bash="$(command -v bash)"
  real_head="$(command -v head)"
  printf '#!/bin/sh\nexec "%s" "$@"\n' "$real_bash" >"$fakebin/bash"
  printf '#!/bin/sh\nexec "%s" "$@"\n' "$real_head" >"$fakebin/head"
  chmod +x "$fakebin/bash"
  chmod +x "$fakebin/head"
}

test_missing_tailscale_binary() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  install_fake_bash "$fakebin"

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$fakebin/systemctl"

  set +e
  local output
  output="$(PATH="$fakebin" bash "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "[tailscale] missing required command: tailscale"
}

mk_stub_cmds_logged_out() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" && "${2:-}" == "--json" ]]; then
  printf '{"BackendState":"NeedsLogin"}\n'
  exit 0
fi
if [[ "$1" == "status" ]]; then
  echo "Logged out."
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
if [[ "$1" == "cert" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_logged_in() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" && "${2:-}" == "--json" ]]; then
  printf '{"BackendState":"Running"}\n'
  exit 0
fi
if [[ "$1" == "status" ]]; then
  echo "100.64.0.10  laptop  linux   active"
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
if [[ "$1" == "cert" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_status_failure() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" && "${2:-}" == "--json" ]]; then
  echo "transport down" >&2
  exit 1
fi
if [[ "$1" == "status" ]]; then
  echo "backend unavailable" >&2
  exit 1
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_logged_in_missing_ipv4() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" && "${2:-}" == "--json" ]]; then
  printf '{"BackendState":"Running"}\n'
  exit 0
fi
if [[ "$1" == "status" ]]; then
  echo "100.64.0.10  laptop  linux   active"
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_json_unavailable_logged_out_fallback() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" && "${2:-}" == "--json" ]]; then
  echo "unknown flag: --json" >&2
  exit 1
fi
if [[ "$1" == "status" ]]; then
  echo "Logged out."
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_json_unavailable_unknown_fallback() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" && "${2:-}" == "--json" ]]; then
  echo "unknown flag: --json" >&2
  exit 1
fi
if [[ "$1" == "status" ]]; then
  echo "100.64.0.10  laptop  linux   active"
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_daemon_activation_fail() {
  local fakebin="$1"
  install_fake_bash "$fakebin"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 3
fi
if [[ "$1" == "enable" ]]; then
  exit 1
fi
exit 0
EOF
  cat >"$fakebin/sudo" <<'EOF'
#!/usr/bin/env bash
"$@"
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/sudo" "$fakebin/tailscale"
}

test_tailscale_status_failure_returns_1() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_status_failure "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "[tailscale] failed to query tailscale status"
  assert_contains "$output" "transport down"
  assert_contains "$output" "backend unavailable"
}

test_daemon_activation_failure_returns_1_with_debug() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_daemon_activation_fail "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "[tailscale] failed to start tailscaled"
  assert_contains "$output" "[tailscale] debug: sudo journalctl -u tailscaled --no-pager -n 50"
}

test_logged_out_returns_10_and_prints_next_step() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_logged_out "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 10 ]]
  assert_contains "$output" "[tailscale] login required"
  assert_contains "$output" "tailscale up --ssh"
}

test_logged_in_without_ipv4_returns_1_and_does_not_print_ready() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_logged_in_missing_ipv4 "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "[tailscale] logged in but no IPv4 assigned"
  assert_not_contains "$output" "[tailscale] ready"
}

test_logged_in_with_ipv4_returns_0_and_prints_status() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_logged_in "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 0 ]]
  assert_contains "$output" "[tailscale] ready"
  assert_contains "$output" "100.64.0.10"
}

test_json_unavailable_logged_out_fallback_returns_10() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_json_unavailable_logged_out_fallback "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 10 ]]
  assert_contains "$output" "[tailscale] login required"
}

test_json_unavailable_unknown_fallback_returns_1() {
  local fakebin
  fakebin="$(mktemp -d)"
  trap 'rm -rf "$fakebin"' RETURN
  mk_stub_cmds_json_unavailable_unknown_fallback "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "[tailscale] unable to determine login state"
  assert_not_contains "$output" "[tailscale] ready"
}

test_missing_tailscale_binary
test_tailscale_status_failure_returns_1
test_daemon_activation_failure_returns_1_with_debug
test_logged_out_returns_10_and_prints_next_step
test_logged_in_without_ipv4_returns_1_and_does_not_print_ready
test_logged_in_with_ipv4_returns_0_and_prints_status
test_json_unavailable_logged_out_fallback_returns_10
test_json_unavailable_unknown_fallback_returns_1
printf 'PASS: setup-tailscale contract tests\n'
