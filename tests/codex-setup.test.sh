#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/codex-setup.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

# A fake codex records every call and answers login and MCP status from env.
make_fakes() {
  local tmp="$1"
  mkdir -p "$tmp/bin" "$tmp/home/.codex"
  cat >"$tmp/bin/codex" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TEST_LOG"
case "$*" in
  "login status") printf '%s\n' "$FAKE_LOGIN" ;;
  *"mcp list --json"*) printf '[{"name":"composio","auth_status":"%s"}]\n' "$FAKE_MCP_AUTH" ;;
esac
exit 0
EOF
  chmod +x "$tmp/bin/codex"
  printf 'model_reasoning_effort = "medium"\n' >"$tmp/config.toml"
}

test_logged_in_is_idempotent() {
  local tmp output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  make_fakes "$tmp"
  ln -s "$tmp/config.toml" "$tmp/home/.codex/config.toml"
  : >"$tmp/log"

  output="$(PATH="$tmp/bin:$PATH" HOME="$tmp/home" TEST_LOG="$tmp/log" \
    FAKE_LOGIN="Logged in using ChatGPT" FAKE_MCP_AUTH="o_auth" "$SUT" 2>&1)"

  ! grep -qx 'login' "$tmp/log"
  ! grep -q 'mcp login' "$tmp/log"
  ! grep -q 'mcp add' "$tmp/log"
  assert_contains "$output" "Codex setup complete"
  assert_contains "$output" "/hooks"
}

test_first_run_logs_in_and_authorizes_composio() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  make_fakes "$tmp"
  ln -s "$tmp/config.toml" "$tmp/home/.codex/config.toml"
  : >"$tmp/log"

  PATH="$tmp/bin:$PATH" HOME="$tmp/home" TEST_LOG="$tmp/log" \
    FAKE_LOGIN="Not logged in" FAKE_MCP_AUTH="not_logged_in" "$SUT" >/dev/null 2>&1

  grep -qx 'login' "$tmp/log"
  grep -qx -- '-c mcp_servers.composio.url="https://connect.composio.dev/mcp" mcp login composio' "$tmp/log"
  # The provider is authorized for the isolated child, never registered.
  ! grep -q 'mcp add' "$tmp/log"
}

test_unstowed_config_fails() {
  local tmp output rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  make_fakes "$tmp"
  cp "$tmp/config.toml" "$tmp/home/.codex/config.toml"
  : >"$tmp/log"

  set +e
  output="$(PATH="$tmp/bin:$PATH" HOME="$tmp/home" TEST_LOG="$tmp/log" \
    FAKE_LOGIN="Logged in" FAKE_MCP_AUTH="o_auth" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "is not stowed"
}

test_root_is_refused() {
  local tmp output rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  make_fakes "$tmp"
  printf '#!/bin/sh\necho 0\n' >"$tmp/bin/id"
  chmod +x "$tmp/bin/id"
  : >"$tmp/log"

  set +e
  output="$(PATH="$tmp/bin:$PATH" HOME="$tmp/home" TEST_LOG="$tmp/log" \
    FAKE_LOGIN="Not logged in" FAKE_MCP_AUTH="not_logged_in" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "not with sudo"
  [[ ! -s "$tmp/log" ]]
}

test_logged_in_is_idempotent
test_first_run_logs_in_and_authorizes_composio
test_unstowed_config_fails
test_root_is_refused
echo "PASS: codex-setup contract tests"
