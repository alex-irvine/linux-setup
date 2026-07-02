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

test_missing_tailscale_binary() {
  local fakebin
  fakebin="$(mktemp -d)"

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$fakebin/systemctl"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "[tailscale] missing required command: tailscale"
}

test_missing_tailscale_binary
printf 'PASS: setup-tailscale contract test (missing binary)\n'
