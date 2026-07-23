#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/mem0-setup.sh"

assert_contains() {
  local haystack="$1" needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

new_tmp() { mktemp -d; }

fake_hermes_logging_argv() {
  local dir="$1"
  cat >"$dir/hermes" <<'EOF'
#!/usr/bin/env bash
echo "hermes-called: $*" >>"$TEST_LOG"
exit 0
EOF
  chmod +x "$dir/hermes"
}

fake_claude_logging_argv() {
  local dir="$1"
  cat >"$dir/claude" <<'EOF'
#!/usr/bin/env bash
echo "claude-called: $*" >>"$TEST_LOG"
exit 0
EOF
  chmod +x "$dir/claude"
}

# Mirrors the real `copilot mcp get <name>` contract: exit 0 if $COPILOT_MCP_HAS_MEM0
# is set (simulating an existing "mem0" entry), exit 1 otherwise. `mcp add` just logs.
fake_copilot_logging_argv() {
  local dir="$1"
  cat >"$dir/copilot" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "mcp" && "$2" == "get" ]]; then
  if [[ -n "${COPILOT_MCP_HAS_MEM0:-}" ]]; then
    echo "copilot-called: $*" >>"$TEST_LOG"
    exit 0
  fi
  echo "copilot-called: $*" >>"$TEST_LOG"
  exit 1
fi
echo "copilot-called: $*" >>"$TEST_LOG"
exit 0
EOF
  chmod +x "$dir/copilot"
}

test_writes_central_key_when_missing() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    CLAUDE_CMD="$tmp/does-not-exist-claude" COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q '^MEM0_API_KEY=m0-test-key$' "$tmp/mem0cfg/env"
  [[ "$(stat -c '%a' "$tmp/mem0cfg/env")" == "600" ]]
  assert_contains "$output" "wrote central key"
}

test_skips_prompt_when_key_already_present() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin" "$tmp/mem0cfg"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"
  printf 'MEM0_API_KEY=m0-existing\n' >"$tmp/mem0cfg/env"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    CLAUDE_CMD="$tmp/does-not-exist-claude" COPILOT_CMD="$tmp/does-not-exist-copilot" \
    "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q '^MEM0_API_KEY=m0-existing$' "$tmp/mem0cfg/env"
  assert_contains "$output" "central key already present"
}

test_appends_zshrc_export_idempotently() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    CLAUDE_CMD="$tmp/does-not-exist-claude" COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1
  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    CLAUDE_CMD="$tmp/does-not-exist-claude" COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1

  local count
  count="$(grep -cF '# mem0-setup: source central Mem0 key' "$tmp/zshrc")"
  if [[ "$count" -ne 1 ]]; then
    printf 'ASSERT FAILED: expected marker exactly once, found %s\n' "$count"
    cat "$tmp/zshrc"
    return 1
  fi
  grep -qF "$tmp/mem0cfg/env" "$tmp/zshrc"
}

test_ensures_hermes_env_key_matches_central() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    CLAUDE_CMD="$tmp/does-not-exist-claude" COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1

  grep -q '^MEM0_API_KEY=m0-test-key$' "$tmp/hermes.env"
}

test_activates_hermes_provider_with_correct_flags() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" CLAUDE_CMD="$tmp/does-not-exist-claude" \
    COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" MEM0_USER_ID="alex" "$SUT" >/dev/null 2>&1

  assert_contains "$(cat "$tmp/log")" "hermes-called: config set memory.provider mem0"
  grep -q '"user_id": "alex"' "$tmp/mem0.json"
  grep -q '"mode": "platform"' "$tmp/mem0.json"
}

test_mem0_json_idempotent_when_user_id_already_matches() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"
  printf '{\n  "mode": "platform",\n  "user_id": "alex",\n  "agent_id": "custom"\n}\n' >"$tmp/mem0.json"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" CLAUDE_CMD="$tmp/does-not-exist-claude" \
    COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" MEM0_USER_ID="alex" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q '"agent_id": "custom"' "$tmp/mem0.json"
  assert_contains "$output" "already has user_id=alex"
}

test_configures_claude_plugin_when_claude_present() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"; fake_claude_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1

  assert_contains "$(cat "$tmp/log")" \
    'claude-called: plugin install mem0@mem0-plugins --config api_key=m0-test-key'
}

test_skips_claude_config_when_claude_absent() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" CLAUDE_CMD="$tmp/does-not-exist-claude" \
    COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "claude not installed, skipping plugin config"
}

test_registers_copilot_mcp_when_copilot_present_and_unregistered() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"; fake_copilot_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" CLAUDE_CMD="$tmp/does-not-exist-claude" \
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1

  assert_contains "$(cat "$tmp/log")" "copilot-called: mcp get mem0"
  assert_contains "$(cat "$tmp/log")" \
    'copilot-called: mcp add --transport http mem0 https://mcp.mem0.ai/mcp/ --header Authorization: Token m0-test-key'
}

test_skips_copilot_registration_when_already_present() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"; fake_copilot_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" CLAUDE_CMD="$tmp/does-not-exist-claude" \
    COPILOT_MCP_HAS_MEM0=1 \
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1

  assert_contains "$(cat "$tmp/log")" "copilot-called: mcp get mem0"
  if grep -q "copilot-called: mcp add" "$tmp/log"; then
    printf 'ASSERT FAILED: expected mcp add NOT to be called, but it was\n'
    cat "$tmp/log"
    return 1
  fi
}

test_skips_copilot_when_copilot_absent() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    HERMES_MEM0_JSON="$tmp/mem0.json" CLAUDE_CMD="$tmp/does-not-exist-claude" \
    COPILOT_CMD="$tmp/does-not-exist-copilot" \
    MEM0_API_KEY="m0-test-key" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "copilot not installed, skipping mcp config"
}

test_missing_hermes_command_fails_clearly() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  set +e
  output="$(TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    MEM0_API_KEY="m0-test-key" HERMES_CMD="$tmp/does-not-exist-hermes" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -ne 0 ]]
  assert_contains "$output" "hermes not installed"
}

test_writes_central_key_when_missing
test_skips_prompt_when_key_already_present
test_appends_zshrc_export_idempotently
test_ensures_hermes_env_key_matches_central
test_activates_hermes_provider_with_correct_flags
test_mem0_json_idempotent_when_user_id_already_matches
test_configures_claude_plugin_when_claude_present
test_skips_claude_config_when_claude_absent
test_registers_copilot_mcp_when_copilot_present_and_unregistered
test_skips_copilot_registration_when_already_present
test_skips_copilot_when_copilot_absent
test_missing_hermes_command_fails_clearly
echo "PASS: mem0-setup contract tests"
