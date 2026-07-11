#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/hermes-setup.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

test_missing_firecrawl_repo_fails() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  cat >"$tmp/bin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$tmp/bin/hermes" "$tmp/bin/docker"

  set +e
  output="$(PATH="$tmp/bin:$PATH" FIRECRAWL_DIR="$tmp/nope" RESTORE_SCRIPT="$tmp/restore-hermes.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "missing Firecrawl repo"
}

test_writes_required_env_keys_and_calls_restore() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin" "$tmp/firecrawl"
  : >"$tmp/log"

  cat >"$tmp/bin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >>"$TEST_LOG"
exit 0
EOF
  cat >"$tmp/restore-hermes.sh" <<'EOF'
#!/usr/bin/env bash
echo "restore-called" >>"$TEST_LOG"
exit 0
EOF
  chmod +x "$tmp/bin/hermes" "$tmp/bin/docker" "$tmp/restore-hermes.sh"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" FIRECRAWL_DIR="$tmp/firecrawl" RESTORE_SCRIPT="$tmp/restore-hermes.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q '^PORT=3002$' "$tmp/firecrawl/.env"
  grep -q '^HOST=0.0.0.0$' "$tmp/firecrawl/.env"
  grep -q '^USE_DB_AUTHENTICATION=false$' "$tmp/firecrawl/.env"
  grep -q '^BULL_AUTH_KEY=' "$tmp/firecrawl/.env"
  grep -q 'docker compose up -d' "$tmp/log"
  grep -q 'restore-called' "$tmp/log"
  assert_contains "$output" "Hermes + Firecrawl setup complete"
}

test_missing_firecrawl_repo_fails
test_writes_required_env_keys_and_calls_restore
echo "PASS: hermes-setup contract tests"
