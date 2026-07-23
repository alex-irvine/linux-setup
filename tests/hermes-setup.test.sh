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

test_builds_product_ops_and_calls_restore() {
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

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" PRODUCT_OPS_DIR="$tmp/po-missing" RESTORE_SCRIPT="$tmp/restore-hermes.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q 'restore-called' "$tmp/log"
  # product-operations build step runs (non-fatal when the source dir is absent)
  assert_contains "$output" "product-operations"
  assert_contains "$output" "Hermes setup complete"
  # docker/firecrawl bring-up is gone -- must not appear anywhere in output
  [[ "$output" != *"docker compose"* ]]
  [[ "$output" != *"Firecrawl repo"* ]]
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

  set +e
  output="$(PATH="$tmp/bin:$PATH" PRODUCT_OPS_DIR="$tmp/po-missing" RESTORE_SCRIPT="$tmp/nope.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "restore script missing"
}

test_builds_product_ops_and_calls_restore
test_missing_restore_script_fails
echo "PASS: hermes-setup contract tests"
