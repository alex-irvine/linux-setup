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

test_existing_product_ops_calls_restore() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  : >"$tmp/log"

  mkdir -p "$tmp/bin"
  cat >"$tmp/bin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$tmp/restore-hermes.sh" <<'EOF'
#!/usr/bin/env bash
echo "restore-called" >>"$TEST_LOG"
exit 0
EOF
  chmod +x "$tmp/bin/hermes" "$tmp/restore-hermes.sh"
  mkdir -p "$tmp/po/.venv/bin"
  printf '#!%s/.venv/bin/python\n' "$tmp/po" >"$tmp/po/.venv/bin/product-ops-mcp"
  chmod +x "$tmp/po/.venv/bin/product-ops-mcp"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" PRODUCT_OPS_DIR="$tmp/po" RESTORE_SCRIPT="$tmp/restore-hermes.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q 'restore-called' "$tmp/log"
  assert_contains "$output" "product-operations venv already built"
  assert_contains "$output" "Hermes setup complete"
  # docker/firecrawl bring-up is gone -- must not appear anywhere in output
  [[ "$output" != *"docker compose"* ]]
  [[ "$output" != *"Firecrawl repo"* ]]
}

test_missing_bots_repo_fails() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  printf '#!/usr/bin/env bash\nexit 0\n' >"$tmp/bin/hermes"
  chmod +x "$tmp/bin/hermes"

  set +e
  output="$(PATH="$tmp/bin:$PATH" PRODUCT_OPS_DIR="$tmp/missing" RESTORE_SCRIPT=/bin/true "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "run clone-repos.sh first"
}

test_missing_restore_script_fails() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  cat >"$tmp/bin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$tmp/bin/hermes"
  mkdir -p "$tmp/po/.venv/bin"
  printf '#!%s/.venv/bin/python\n' "$tmp/po" >"$tmp/po/.venv/bin/product-ops-mcp"
  chmod +x "$tmp/po/.venv/bin/product-ops-mcp"

  set +e
  output="$(PATH="$tmp/bin:$PATH" PRODUCT_OPS_DIR="$tmp/po" RESTORE_SCRIPT="$tmp/nope.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "restore script missing"
}

test_existing_product_ops_calls_restore
test_missing_bots_repo_fails
test_missing_restore_script_fails
echo "PASS: hermes-setup contract tests"
