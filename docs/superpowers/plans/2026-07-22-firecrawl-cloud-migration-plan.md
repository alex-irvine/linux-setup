# Firecrawl Cloud Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the self-hosted Firecrawl docker-compose stack with Firecrawl's hosted cloud API, decided on measured evidence (the self-hosted instance processed zero requests in its entire lifetime and has had no crash-recovery for 12 days) plus real pricing analysis (Firecrawl's free tier — 1,000 credits/month — comfortably covers this usage pattern).

**Architecture:** `~/.hermes/.env` gains an active `FIRECRAWL_API_KEY` and `FIRECRAWL_API_URL=https://api.firecrawl.dev`. Hermes reads this file directly (confirmed — no hardcoded localhost logic). **OpenCode also needs to authenticate** (its `firecrawl-*` skills shell out to the `firecrawl` CLI via the Bash tool, not an MCP server) — rather than duplicating the key into a second file, a new `firecrawl-setup.sh` seeds `firecrawl-cli`'s own stored-credentials file from the same `~/.hermes/.env`, so `~/.hermes/.env` stays the single place the raw key is ever written, for both consumers. This script runs *before* `hermes-setup.sh` and `opencode-setup.sh` in `endeavouros-setup.sh` (both are downstream of it) — see Task 1. The self-host bring-up logic in `hermes-setup.sh`, the clone entry in `clone-repos.sh`, and the local docker stack are removed/decommissioned. No dotfiles changes needed — `config.yaml`'s `backend: firecrawl` value is unaffected by hosting model.

**Tech Stack:** bash, npm (`firecrawl-cli`), Docker Compose (removal only), Firecrawl hosted API (`https://api.firecrawl.dev`, `Authorization: Bearer <key>`).

## Global Constraints

- This is a **separate plan from the cross-provider memory design** (`agent-lib/docs/2026-07-21-cross-provider-memory-design.md`) — no technical overlap, evaluated only via the same hosted-vs-self-hosted methodology. Do not merge these.
- The API key is a secret: lives only in `~/.hermes/.env` (gitignored, covered by the working `hermes-backup.timer`), never in any repo.
- Obtaining the API key is a manual, external, human-only step (account signup) — cannot be scripted.
- OpenCode must authenticate too, without duplicating the raw key into a second file: `firecrawl-setup.sh` seeds `firecrawl-cli`'s own stored-credentials store from `~/.hermes/.env` at setup time, keeping that one file the sole source of truth (see Task 1).
- `firecrawl-setup.sh` runs before `hermes-setup.sh` and `opencode-setup.sh` in `endeavouros-setup.sh` — confirmed safe because Hermes's own installer only creates `~/.hermes/.env` `if [ ! -f ... ]` and never clobbers a pre-existing one.
- Destructive local operations (removing the docker stack, deleting `~/Proj/firecrawl`) must be explicit, confirmed steps — never silently bundled into another task.
- `docs-hermes-firecrawl.test.sh`'s existing assertions (`"Runs hermes-setup.sh"`, `"~/Proj/linux-setup/restore-hermes.sh"`, absence of `"~/.hermes/scripts/restore-hermes.sh"`, `"same-host"`) must still all pass — none reference firecrawl specifics directly, so they constrain wording but don't need editing themselves.

---

### Task 1: Provision the Firecrawl credential for both Hermes and OpenCode

**Files:**
- Create: `~/Proj/linux-setup/firecrawl-setup.sh`
- Create: `~/Proj/linux-setup/tests/firecrawl-setup.test.sh`
- Modify: `~/Proj/linux-setup/endeavouros-setup.sh` (call site, before `opencode-setup.sh`/`hermes-setup.sh`)
- Modify: `~/.hermes/.env` (not in any repo — runtime secrets file; written by `firecrawl-setup.sh`, not by hand)

**Interfaces:**
- Produces: an active `FIRECRAWL_API_KEY=fc-...` and `FIRECRAWL_API_URL=https://api.firecrawl.dev` in `~/.hermes/.env` (Hermes reads this file directly — unchanged from the original design), **and** a seeded `firecrawl-cli` stored-credentials file (`~/.config/firecrawl-cli/credentials.json` on Linux) that OpenCode's Bash-tool-invoked `firecrawl-*` skills authenticate through. No opencode.jsonc/MCP change needed: OpenCode has no documented `.env`-loading convention, but `firecrawl-cli` itself checks the `FIRECRAWL_API_KEY` env var, then falls back to this stored-credentials file — seeding it here means every `firecrawl` invocation (OpenCode's Bash tool, or a bare terminal) authenticates the same way, with `~/.hermes/.env` as the one place the raw key is ever written. Task 7's end-to-end check exercises this path for real.
- Consumes: nothing from other tasks. This is still the first task, but it now runs **before** both `hermes-setup.sh` and `opencode-setup.sh` in `endeavouros-setup.sh` — both are downstream consumers of the credential it provisions, not the other way around.

**Why a dedicated script, not just a manual `.env` edit:** the original version of this task was human-run shell commands with no fresh-install story, and only covered Hermes. Extracting the logic into `firecrawl-setup.sh`, ordered before `hermes-setup.sh` *and* `opencode-setup.sh`, makes a fresh OS install reproduce this exact setup (once the human step below has been done, on any machine). Running it before Hermes exists is safe: Hermes's own remote installer (`hermes-agent.nousresearch.com/install.sh`) only writes `~/.hermes/.env` `if [ ! -f "$HERMES_HOME/.env" ]`, and logs `"~/.hermes/.env already exists, keeping it"` otherwise (confirmed by reading that installer directly) — it can never clobber a file this script pre-seeds.

**Interactive but never blocking:** if no key is set yet and the script is running at a real terminal (`[[ -t 0 ]]`), it prompts for one (silently, via `read -s`, and writes it to `ENV_FILE` if given). If run unattended (piped, no controlling terminal — e.g. an automated fresh-install) or the prompt is left blank, it soft-skips instead of hanging: leaves a commented placeholder, logs instructions, exits 0. Either way it's idempotent — safe to skip now and simply re-run later once a key exists, at which point the "already set" fast path (no prompt, straight to reseeding) takes over.

- [x] **Step 1: Sign up and get an API key (manual, human-only)**

Go to https://firecrawl.dev/, sign up (or sign in), open the dashboard, and copy your API key (starts with `fc-`). This cannot be automated — no account exists yet to script against.

- [x] **Step 2: Create `firecrawl-setup.sh`**

Full content:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Runs BEFORE opencode-setup.sh and hermes-setup.sh -- both are downstream
# consumers of the credential this script provisions (Hermes reads
# FIRECRAWL_API_KEY/FIRECRAWL_API_URL straight out of ENV_FILE; OpenCode's
# firecrawl-* skills shell out to the `firecrawl` CLI, which authenticates
# via its own stored-credentials file, seeded below). If no key is set yet
# and this is running at an interactive terminal, prompts for one; otherwise
# soft-skips so unattended/automated runs never block. Idempotent either
# way -- safe to skip now and re-run later once you have a key.
ENV_FILE="${FIRECRAWL_ENV_FILE:-$HOME/.hermes/.env}"

log() { printf '[firecrawl-setup] %s\n' "$*"; }
err() { printf '[firecrawl-setup] %s\n' "$*" >&2; }

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "missing required command: $1"
    exit 1
  }
}

ensure_env_key_if_missing() {
  local file="$1"
  local key="$2"
  local value="$3"
  grep -q "^${key}=" "$file" 2>/dev/null || printf '%s=%s\n' "$key" "$value" >>"$file"
}

read_env_key() {
  local file="$1"
  local key="$2"
  # `|| true`: grep exits 1 on "no match" (the expected case when the key
  # isn't set yet), which pipefail would otherwise propagate and, under
  # set -e, kill the whole script right when it needs to soft-skip instead.
  grep "^${key}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

# Removes any existing line for $key (commented placeholder or live value)
# and appends a fresh one. Deliberately not sed-based: the value is a
# secret the user just typed, and sed substitution treats it as a
# pattern/replacement (breaks on &, |, \). Here it's only ever interpolated
# via printf '%s', so no characters need escaping.
set_env_key() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp)"
  grep -v -E "^#? ?${key}=" "$file" 2>/dev/null >"$tmp" || true
  printf '%s=%s\n' "$key" "$value" >>"$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
}

# Overridable for tests, which have no real controlling terminal:
# FIRECRAWL_SETUP_INTERACTIVE unset -> real `-t 0` check (production
# default, zero config). Set to "1"/"0" to force the answer either way.
is_interactive() {
  if [[ -n "${FIRECRAWL_SETUP_INTERACTIVE:-}" ]]; then
    [[ "$FIRECRAWL_SETUP_INTERACTIVE" == "1" ]]
    return
  fi
  [[ -t 0 ]]
}

main() {
  ensure_cmd npm

  # Safe to create ENV_FILE before Hermes itself is installed: Hermes's own
  # installer only writes it `if [ ! -f "$HERMES_HOME/.env" ]`, and logs
  # "~/.hermes/.env already exists, keeping it" otherwise -- confirmed
  # non-destructive, never clobbers a pre-existing file.
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  ensure_env_key_if_missing "$ENV_FILE" "FIRECRAWL_API_URL" "https://api.firecrawl.dev"

  if ! command -v firecrawl >/dev/null 2>&1; then
    log "installing firecrawl-cli"
    npm install -g firecrawl-cli
  fi

  local key
  key="$(read_env_key "$ENV_FILE" "FIRECRAWL_API_KEY")"

  if [[ -z "$key" ]] && is_interactive; then
    log "no FIRECRAWL_API_KEY set in $ENV_FILE yet"
    printf '[firecrawl-setup] Enter your Firecrawl API key (https://firecrawl.dev/, blank to skip for now): ' >&2
    read -r -s key
    echo >&2
    if [[ -n "$key" ]]; then
      set_env_key "$ENV_FILE" "FIRECRAWL_API_KEY" "$key"
      log "saved FIRECRAWL_API_KEY to $ENV_FILE"
    fi
  fi

  if [[ -z "$key" ]]; then
    grep -q '^# FIRECRAWL_API_KEY=' "$ENV_FILE" 2>/dev/null || printf '# FIRECRAWL_API_KEY=fc-your-key-here\n' >>"$ENV_FILE"
    log "no FIRECRAWL_API_KEY set in $ENV_FILE yet"
    log "sign up at https://firecrawl.dev/, then re-run this script (prompts for it"
    log "interactively), or uncomment and set it in $ENV_FILE by hand"
    log "firecrawl-cli installed; keyless free tier active until then (rate-limited)"
    return 0
  fi

  log "seeding firecrawl-cli stored credentials from $ENV_FILE"
  firecrawl login --api-key "$key" >/dev/null

  log "firecrawl-setup complete (Hermes reads $ENV_FILE directly; OpenCode's firecrawl-* skills use the CLI's stored credentials just seeded)"
}

main "$@"
```

Then: `chmod +x ~/Proj/linux-setup/firecrawl-setup.sh`

- [x] **Step 3: Wire it into `endeavouros-setup.sh`, before both downstream consumers**

Insert immediately before the existing `echo "==== Running opencode-setup.sh ===="` line:

```bash
###########################################################
# Firecrawl (installs firecrawl-cli, ensures FIRECRAWL_API_KEY/URL exist in
# ~/.hermes/.env, seeds the CLI's own stored credentials). Runs before
# opencode-setup.sh and hermes-setup.sh -- both are downstream consumers of
# this credential (Hermes reads the env file directly; OpenCode's
# firecrawl-* skills shell out to the CLI, authenticated via its stored
# credentials). Safe to run before Hermes is installed -- see
# firecrawl-setup.sh's own comments for why it can't clobber Hermes's env.
###########################################################
echo "==== Running firecrawl-setup.sh ===="
bash "$SCRIPT_DIR/firecrawl-setup.sh"

```

- [x] **Step 4: Write `tests/firecrawl-setup.test.sh` and run it**

Full content:

```bash
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
```

Run: `bash ~/Proj/linux-setup/tests/firecrawl-setup.test.sh`
Expected: `PASS: firecrawl-setup contract tests`

- [x] **Step 5: Run the real script once against this machine**

Run: `bash ~/Proj/linux-setup/firecrawl-setup.sh`
Expected: logs `seeding firecrawl-cli stored credentials from ~/.hermes/.env` then `firecrawl-setup complete (...)`. Verify with `firecrawl --status` → `Authenticated via stored credentials`.

- [x] **Step 6: Smoke-test the cloud endpoint directly (one-time — not part of the reusable script, since it costs a credit on every run)**

Run (uses the key from your shell, never echoes it):
```bash
curl -s -o /tmp/firecrawl-smoke.json -w '%{http_code}\n' \
  -X POST https://api.firecrawl.dev/v1/scrape \
  -H "Authorization: Bearer $(grep '^FIRECRAWL_API_KEY=' ~/.hermes/.env | cut -d= -f2-)" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
cat /tmp/firecrawl-smoke.json | head -c 300; echo
rm -f /tmp/firecrawl-smoke.json
```
Expected: HTTP `200`, and the JSON body contains markdown content from example.com. If `401`, the key wasn't saved correctly — recheck Step 2. This is the first real request this account has ever made — expect it to consume 1 credit, confirming billing/auth actually works end-to-end.

---

### Task 2: Remove the self-host bring-up from `hermes-setup.sh`

**Files:**
- Modify: `~/Proj/linux-setup/hermes-setup.sh`

**Interfaces:**
- Consumes: nothing from Task 1 (this task only removes code).
- Produces: a `hermes-setup.sh` with no `docker`/`FIRECRAWL_DIR` references, which Task 3's test rewrite depends on.

- [x] **Step 1: Remove the `FIRECRAWL_DIR` variable and the `docker` requirement**

In `hermes-setup.sh`, remove line 5 (`FIRECRAWL_DIR="${FIRECRAWL_DIR:-$HOME/Proj/firecrawl}"`) and remove `ensure_cmd docker` from `main()` (currently the first line of `main()`, right after the `main() {` opening) — nothing else in this script uses docker once the bring-up block below is removed.

- [x] **Step 2: Remove the entire firecrawl bring-up block from `main()`**

Delete this whole block (currently between `install_hermes_if_missing`/`ensure_cmd hermes` and `build_product_operations`):

```bash
  if [[ ! -d "$FIRECRAWL_DIR" ]]; then
    err "missing Firecrawl repo at: $FIRECRAWL_DIR"
    err "run clone-repos.sh or full bootstrap first"
    exit 1
  fi

  mkdir -p "$FIRECRAWL_DIR"
  : >"$FIRECRAWL_DIR/.env.tmp"
  if [[ -f "$FIRECRAWL_DIR/.env" ]]; then
    cat "$FIRECRAWL_DIR/.env" >"$FIRECRAWL_DIR/.env.tmp"
  fi

  ensure_env_key_if_missing "$FIRECRAWL_DIR/.env.tmp" "PORT" "3002"
  ensure_env_key_if_missing "$FIRECRAWL_DIR/.env.tmp" "HOST" "0.0.0.0"
  ensure_env_key_if_missing "$FIRECRAWL_DIR/.env.tmp" "USE_DB_AUTHENTICATION" "false"
  if ! grep -q '^BULL_AUTH_KEY=' "$FIRECRAWL_DIR/.env.tmp"; then
    ensure_cmd openssl
    printf 'BULL_AUTH_KEY=%s\n' "$(openssl rand -hex 16)" >>"$FIRECRAWL_DIR/.env.tmp"
  fi
  mv "$FIRECRAWL_DIR/.env.tmp" "$FIRECRAWL_DIR/.env"

  if (cd "$FIRECRAWL_DIR" && docker compose up -d); then
    :
  else
    rc=$?
    err "failed to start Firecrawl docker compose stack"
    err "run: cd \"$FIRECRAWL_DIR\" && docker compose logs"
    exit "$rc"
  fi

```

Also remove the now-unused `ensure_env_key_if_missing` helper function (lines 18-25) — it existed only to build the firecrawl `.env`, and nothing else in this script calls it.

- [x] **Step 3: Update the final log message**

Change:
```bash
  log "Hermes + Firecrawl setup complete"
```
to:
```bash
  log "Hermes setup complete (Firecrawl via cloud API)"
```

- [x] **Step 4: Syntax-check**

Run: `bash -n ~/Proj/linux-setup/hermes-setup.sh && echo OK`
Expected: `OK`.

---

### Task 3: Rewrite `hermes-setup.test.sh` for the simplified script

**Files:**
- Modify: `~/Proj/linux-setup/tests/hermes-setup.test.sh`

**Interfaces:**
- Consumes: the simplified `hermes-setup.sh` from Task 2 (no `FIRECRAWL_DIR`, no docker, new log message).
- Produces: a passing test file with no firecrawl/docker assertions.

- [x] **Step 1: Replace the whole file**

The `test_missing_firecrawl_repo_fails` and `test_compose_failure_prints_logs_remediation` tests are entirely about behavior that no longer exists (delete both). `test_writes_required_env_keys_and_calls_restore` keeps only its product-operations + restore assertions. Replace the full file content with:

```bash
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
```

- [x] **Step 2: Run it**

Run: `bash ~/Proj/linux-setup/tests/hermes-setup.test.sh`
Expected: `PASS: hermes-setup contract tests`

---

### Task 4: Remove the firecrawl clone from `clone-repos.sh` and update its test

**Files:**
- Modify: `~/Proj/linux-setup/clone-repos.sh`
- Modify: `~/Proj/linux-setup/tests/clone-repos-firecrawl-wireup.test.sh`

**Interfaces:**
- Produces: `clone-repos.sh` with no firecrawl clone step; a test asserting its intentional absence (regression guard, same pattern already used elsewhere in this codebase for "must NOT reappear" checks).

- [x] **Step 1: Remove the firecrawl clone block**

In `clone-repos.sh`, remove:
```bash
echo "==== Cloning Firecrawl ===="
clone_or_pull https://github.com/firecrawl/firecrawl.git ~/Proj/firecrawl
```

- [x] **Step 2: Update the test to assert absence, not presence**

Replace the full content of `clone-repos-firecrawl-wireup.test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/clone-repos.sh"
CONTENT="$(cat "$FILE")"

# Firecrawl migrated to the hosted cloud API (2026-07-22) -- must NOT be
# cloned/self-hosted again without revisiting that decision.
[[ "$CONTENT" != *"firecrawl/firecrawl.git"* ]] || {
  echo "FAIL: firecrawl clone re-added to clone-repos.sh -- see docs/superpowers/plans/2026-07-22-firecrawl-cloud-migration-plan.md"
  exit 1
}

[[ "$CONTENT" == *"agent-lib.git"* && "$CONTENT" == *"~/Proj/agent-lib"* ]] || {
  echo "FAIL: agent-lib clone wireup missing in clone-repos.sh"
  exit 1
}

echo "PASS: agent-lib clone wireup present; firecrawl clone intentionally absent"
```

- [x] **Step 3: Run it**

Run: `bash ~/Proj/linux-setup/tests/clone-repos-firecrawl-wireup.test.sh`
Expected: `PASS: agent-lib clone wireup present; firecrawl clone intentionally absent`

---

### Task 5: Update README and run the full test suite

**Files:**
- Modify: `~/Proj/linux-setup/README.md:37`

**Interfaces:**
- Consumes: nothing new.
- Produces: README wording consistent with the cloud-only setup; must keep the exact substring `"Runs hermes-setup.sh"` (asserted by `docs-hermes-firecrawl.test.sh:8`).

- [x] **Step 1: Update the step-6 description**

Change:
```markdown
6. Runs hermes-setup.sh (Hermes install, Firecrawl self-host bring-up,
   product-operations venv build, restore bootstrap).
```
to:
```markdown
6. Runs `firecrawl-setup.sh` first (installs firecrawl-cli, seeds its
   stored credentials, ensures `~/.hermes/.env` has `FIRECRAWL_API_KEY`/
   `FIRECRAWL_API_URL` — both Hermes and OpenCode's firecrawl-* skills
   read from this single source; see
   docs/superpowers/plans/2026-07-22-firecrawl-cloud-migration-plan.md).
   Runs hermes-setup.sh (Hermes install, product-operations venv build,
   restore bootstrap).
```

(This preserves the literal substring `"Runs hermes-setup.sh"` required by the existing docs test — it now starts the second sentence instead of the first.)

- [x] **Step 2: Run the full linux-setup test suite**

Run:
```bash
cd ~/Proj/linux-setup
for t in tests/*.test.sh; do printf '%-45s ' "$(basename "$t"):"; bash "$t" >/dev/null 2>&1 && echo PASS || { echo FAIL; bash "$t"; }; done
```
Expected: every test prints `PASS`, including `docs-hermes-firecrawl.test.sh`, `hermes-setup.test.sh`, `firecrawl-setup.test.sh`, and `clone-repos-firecrawl-wireup.test.sh`.

- [x] **Step 3: Commit**

Note: `firecrawl-setup.sh`, `tests/firecrawl-setup.test.sh`, and the
`endeavouros-setup.sh` call-site wiring (Task 1) were already committed and
pushed separately, ahead of this step, as `d1c417a "firecrawl cloud"` —
diff-verified identical to the final working-tree state, including the
interactive-prompt revision. This step commits the remainder (Tasks 2-4's
self-host removal, README):

```bash
cd ~/Proj/linux-setup
git add hermes-setup.sh clone-repos.sh README.md tests/hermes-setup.test.sh tests/clone-repos-firecrawl-wireup.test.sh docs/superpowers/plans/2026-07-22-firecrawl-cloud-migration-plan.md
git commit -m "refactor: migrate Firecrawl from self-hosted to cloud API

Self-hosted instance processed zero requests in its entire lifetime
(created+crashed same day, 2026-07-10, no restart policy, down 12 days
unnoticed) and Firecrawl's free tier (1,000 credits/month) comfortably
covers this usage. Removes the docker-compose bring-up from
hermes-setup.sh and the clone from clone-repos.sh; FIRECRAWL_API_KEY/URL
in ~/.hermes/.env now point at the hosted API instead (firecrawl-setup.sh,
wired before hermes-setup.sh/opencode-setup.sh, already landed in
d1c417a -- also seeds firecrawl-cli's stored credentials there, so
OpenCode's firecrawl-* skills authenticate from the same source, no
duplicated key)."
git push
```

---

### Task 6: Decommission the local docker stack (destructive — explicit, not bundled)

**Files:** none (infrastructure only)

**Interfaces:** none.

- [ ] **Step 1: Confirm Task 1's cloud smoke test passed** before touching the local stack — do not proceed if Task 1 Step 6 didn't return `200`.

- [ ] **Step 2: Stop and remove the local containers + volumes**

Run:
```bash
cd ~/Proj/firecrawl
docker compose down -v
```
Expected: all 6 `firecrawl-*` containers and the `fdb-data`/`fdb-cluster-file` volumes are removed. This reclaims disk space; there is nothing in those volumes worth keeping (confirmed: `nuq`/FoundationDB held only empty-queue reconciler state, zero jobs were ever processed).

- [ ] **Step 3: Verify removal**

Run: `docker ps -a --filter "name=firecrawl"`
Expected: empty output.

- [ ] **Step 4: (Optional, your call) remove the local clone**

The directory is no longer needed once the cloud API is configured and `clone-repos.sh` no longer clones it. If you want it gone:
```bash
rm -rf ~/Proj/firecrawl
```
Not required for correctness — leaving it is harmless, just an unused clone.

---

### Task 7: End-to-end verification

**Files:** none.

- [ ] **Step 1: Trigger a real firecrawl-backed request through the actual skill path** (not a bare curl this time)

Ask the agent to run: "scrape https://example.com and show me the title" (invokes the `firecrawl-scrape` skill, which shells out to the `firecrawl` CLI via OpenCode's Bash tool — authenticated via the stored credentials Task 1 seeded from `~/.hermes/.env`, not a direct env-var read).
Expected: markdown content returned, no auth/connection errors.

- [ ] **Step 2: Confirm it's hitting the cloud account, not a stale local reference**

Log in to your Firecrawl account at https://firecrawl.dev/ and check the usage/credits view for the request from Step 1.
Expected: at least 2 credits consumed total (1 from Task 1 Step 6, 1 from this step) — confirms real cloud usage, not silently falling back to the (now-removed) local stack.

- [ ] **Step 3: Set a monitoring reminder**

Same discipline as the mem0 design doc: the "fits comfortably in free tier" conclusion is reasoned from zero historical usage + moderate realistic estimates, not measured over a full month. Check the Firecrawl dashboard's credit usage after a few weeks of normal use. If ever exceeded, the escalation path is Hobby ($16/mo, 5,000 credits) before ever reconsidering self-hosting — and self-hosting should only be reconsidered with a backup/restore story designed up front, per the same standard set in the memory design doc.

---

## Self-Review

**Spec coverage:** free-tier check → Task 1 Step 6 + Task 7 (real usage confirms it fits); separate-from-mem0 scope → stated in Global Constraints; OpenCode also authenticated (not just Hermes), via a central source rather than a duplicated key → Task 1 (`firecrawl-setup.sh` seeds `firecrawl-cli`'s stored credentials from `~/.hermes/.env`), exercised for real by Task 7; fresh-install parity for that wiring → Task 1 Step 3 (`endeavouros-setup.sh` call site, ordered before both downstream consumers) + Task 1's own test file; remove self-host bring-up → Tasks 2-4; docs → Task 5; safe decommission of local stack → Task 6 (explicit, gated on cloud working first); end-to-end confidence → Task 7. No gaps found.

**Placeholder scan:** no TBD/TODO; every step has literal commands or full file replacements, not descriptions.

**Type/interface consistency:** `hermes-setup.sh`'s final log message (Task 2 Step 3: `"Hermes setup complete"`) matches the test assertion in Task 3 (`assert_contains "$output" "Hermes setup complete"`) and the README wording in Task 5 uses the distinct, separately-asserted substring `"Runs hermes-setup.sh"` — no collision between the two. `firecrawl-setup.sh`'s log lines (`"seeding"`, `"complete"`, `"installing firecrawl-cli"`, `"no FIRECRAWL_API_KEY set"`, `"saved FIRECRAWL_API_KEY"`) match `tests/firecrawl-setup.test.sh`'s `assert_contains` calls exactly.

**Amendment note (post-approval, same day):** Task 1 was rewritten in place twice after the plan was first committed (`8bb2223`) — the original version only wrote `~/.hermes/.env` by hand with no fresh-install story and didn't cover OpenCode. First revision: redesigned and re-verified against this machine (script + tests written, hermetic-PATH test bug and a `pipefail`/`grep`-exit-status bug in `read_env_key` both found and fixed by actually running the tests, real script run end-to-end, `firecrawl --status` confirmed "Authenticated via stored credentials") before folding back into this document. Second revision: added the interactive prompt-if-no-key-and-TTY behavior (`is_interactive`, `set_env_key`, 2 new tests), re-verified the same way (full suite + real run against `~/.hermes/.env` again). Tasks 2-7 were reviewed against both changes and needed no other edits beyond the file-list/README/self-review touch-ups above.
