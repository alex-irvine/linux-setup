#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/firecrawl-setup.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

# Hermetic PATH: symlink only the real coreutils the SUT needs, so a
# pre-existing, real, globally-installed firecrawl-cli on the host machine
# (there is one on this dev box) can never leak into a "not installed" test.
hermetic_bin() {
  local bindir="$1"
  local c
  for c in bash mkdir touch chmod grep cut dirname tail cat mktemp mv; do
    ln -sf "$(command -v "$c")" "$bindir/$c"
  done
}

fake_firecrawl() {
  local bindir="$1"
  local logfile="$2"
  cat >"$bindir/firecrawl" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$logfile"
exit 0
EOF
  chmod +x "$bindir/firecrawl"
}

noop_npm() {
  local bindir="$1"
  cat >"$bindir/npm" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$bindir/npm"
}

test_seeds_credentials_when_cli_already_installed() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  hermetic_bin "$tmp/bin"
  printf 'FIRECRAWL_API_KEY=fc-testkey123\n' >"$tmp/env"
  fake_firecrawl "$tmp/bin" "$tmp/firecrawl-calls"
  cat >"$tmp/bin/npm" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$tmp/npm-calls"
exit 0
EOF
  chmod +x "$tmp/bin/npm"

  set +e
  output="$(PATH="$tmp/bin" FIRECRAWL_ENV_FILE="$tmp/env" FIRECRAWL_SETUP_INTERACTIVE=0 "$SUT" 2>&1 </dev/null)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  [[ ! -e "$tmp/npm-calls" ]] # already installed -- npm must NOT be invoked
  grep -q '^login --api-key fc-testkey123$' "$tmp/firecrawl-calls"
  grep -q '^FIRECRAWL_API_URL=https://api.firecrawl.dev$' "$tmp/env"
  assert_contains "$output" "seeding"
  assert_contains "$output" "complete"
}

test_installs_cli_via_npm_when_missing() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  hermetic_bin "$tmp/bin"
  printf 'FIRECRAWL_API_KEY=fc-testkey123\n' >"$tmp/env"
  # npm "install"s firecrawl by writing the fake binary itself, simulating a real -g install.
  cat >"$tmp/bin/npm" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$tmp/npm-calls"
if [[ "\$*" == *"install -g firecrawl-cli"* ]]; then
  cat >"$tmp/bin/firecrawl" <<'INNER'
#!/usr/bin/env bash
printf '%s\n' "\$*" >>"$tmp/firecrawl-calls"
exit 0
INNER
  chmod +x "$tmp/bin/firecrawl"
fi
exit 0
EOF
  chmod +x "$tmp/bin/npm"

  set +e
  output="$(PATH="$tmp/bin" FIRECRAWL_ENV_FILE="$tmp/env" FIRECRAWL_SETUP_INTERACTIVE=0 "$SUT" 2>&1 </dev/null)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q 'install -g firecrawl-cli' "$tmp/npm-calls"
  grep -q '^login --api-key fc-testkey123$' "$tmp/firecrawl-calls"
  assert_contains "$output" "installing firecrawl-cli"
}

test_no_key_yet_soft_skips() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  hermetic_bin "$tmp/bin"
  : >"$tmp/env" # exists, but no FIRECRAWL_API_KEY line at all
  fake_firecrawl "$tmp/bin" "$tmp/firecrawl-calls"
  noop_npm "$tmp/bin"

  set +e
  output="$(PATH="$tmp/bin" FIRECRAWL_ENV_FILE="$tmp/env" FIRECRAWL_SETUP_INTERACTIVE=0 "$SUT" 2>&1 </dev/null)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  [[ ! -e "$tmp/firecrawl-calls" ]] # login must NOT be called -- no key yet
  grep -q '^# FIRECRAWL_API_KEY=fc-your-key-here$' "$tmp/env"
  assert_contains "$output" "no FIRECRAWL_API_KEY set"
}

test_preserves_existing_env_file_content() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  hermetic_bin "$tmp/bin"
  printf 'SOME_OTHER_KEY=untouched-value\nFIRECRAWL_API_KEY=fc-testkey123\n' >"$tmp/env"
  fake_firecrawl "$tmp/bin" "$tmp/firecrawl-calls"
  noop_npm "$tmp/bin"

  set +e
  output="$(PATH="$tmp/bin" FIRECRAWL_ENV_FILE="$tmp/env" FIRECRAWL_SETUP_INTERACTIVE=0 "$SUT" 2>&1 </dev/null)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q '^SOME_OTHER_KEY=untouched-value$' "$tmp/env" # pre-existing content survives
  grep -q '^FIRECRAWL_API_URL=https://api.firecrawl.dev$' "$tmp/env"
}

test_prompts_and_saves_key_when_interactive() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  hermetic_bin "$tmp/bin"
  : >"$tmp/env" # no key yet
  fake_firecrawl "$tmp/bin" "$tmp/firecrawl-calls"
  noop_npm "$tmp/bin"

  set +e
  output="$(PATH="$tmp/bin" FIRECRAWL_ENV_FILE="$tmp/env" FIRECRAWL_SETUP_INTERACTIVE=1 "$SUT" <<<'fc-prompted999' 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q '^FIRECRAWL_API_KEY=fc-prompted999$' "$tmp/env" # entered value landed, live (not commented)
  grep -q '^login --api-key fc-prompted999$' "$tmp/firecrawl-calls"
  assert_contains "$output" "saved FIRECRAWL_API_KEY"
  assert_contains "$output" "seeding"
  assert_contains "$output" "complete"
}

test_interactive_blank_input_soft_skips() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  hermetic_bin "$tmp/bin"
  : >"$tmp/env" # no key yet
  fake_firecrawl "$tmp/bin" "$tmp/firecrawl-calls"
  noop_npm "$tmp/bin"

  set +e
  output="$(PATH="$tmp/bin" FIRECRAWL_ENV_FILE="$tmp/env" FIRECRAWL_SETUP_INTERACTIVE=1 "$SUT" <<<'' 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  [[ ! -e "$tmp/firecrawl-calls" ]] # blank answer -- login must NOT be called
  grep -q '^# FIRECRAWL_API_KEY=fc-your-key-here$' "$tmp/env"
  assert_contains "$output" "no FIRECRAWL_API_KEY set"
}

test_seeds_credentials_when_cli_already_installed
test_installs_cli_via_npm_when_missing
test_no_key_yet_soft_skips
test_preserves_existing_env_file_content
test_prompts_and_saves_key_when_interactive
test_interactive_blank_input_soft_skips
echo "PASS: firecrawl-setup contract tests"
