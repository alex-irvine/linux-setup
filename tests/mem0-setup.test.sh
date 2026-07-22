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

test_writes_central_key_when_missing() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
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
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1
  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
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
    MEM0_API_KEY="m0-test-key" "$SUT" >/dev/null 2>&1

  grep -q '^MEM0_API_KEY=m0-test-key$' "$tmp/hermes.env"
}

test_activates_hermes_provider_with_correct_flags() {
  local tmp; tmp="$(new_tmp)"; trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/bin"; fake_hermes_logging_argv "$tmp/bin"
  : >"$tmp/log"; : >"$tmp/zshrc"; : >"$tmp/hermes.env"

  PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" \
    MEM0_CONFIG_DIR="$tmp/mem0cfg" HERMES_ENV="$tmp/hermes.env" ZSHRC="$tmp/zshrc" \
    MEM0_API_KEY="m0-test-key" MEM0_USER_ID="alex" "$SUT" >/dev/null 2>&1

  assert_contains "$(cat "$tmp/log")" \
    "hermes-called: memory setup mem0 --mode platform --api-key m0-test-key --user-id alex"
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
test_missing_hermes_command_fails_clearly
echo "PASS: mem0-setup contract tests"
