# Restore-Hermes Hardening + New-Laptop Runbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the automatable/promptable gaps in `restore-hermes.sh` for a genuinely new-laptop restore (cross-host archive selection, root-profile gateway reinstall, offering to configure gdrive), and enshrine the one thing that can never be automated (first OAuth consent) in a new runbook doc.

**Architecture:** Three new/replacement bash functions inside the existing `restore-hermes.sh` (no new files for the script itself), each falling back to today's exact behavior on any ambiguity or failure. Plus one new standalone doc (`NEW-LAPTOP.md`) linked from `README.md`, mirroring the existing `TAILSCALE.md` pattern.

**Tech Stack:** bash (`set -euo pipefail`), `rclone`, `hermes` CLI, `systemctl --user`.

## Global Constraints

- Every new branch's failure/ambiguity mode falls through to today's existing, already-correct behavior — never a new way to hang or hard-fail. (Spec §7)
- No new flags on `restore-hermes.sh` — `--remote`, `--archive`, `--yes`, `--dry-run`, `-h/--help` unchanged; new behavior is tty-aware branching inside the existing flow. (Spec §5)
- No new runtime dependencies (`rclone`/`hermes`/`systemctl` already required). (Spec §6)
- The two genuinely-interactive branches (offering to run `rclone config`; the interactive host picker) are not automated-tested — `/dev/tty` can't be faked like a `PATH` binary, same limitation `install.sh` itself lives with. Verified manually instead (Final Verification Gate). (Spec §8.2)
- `maybe_install_root_gateway()` only checks for *presence* of `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `WHATSAPP_ENABLED` (exact list from `install.sh:2310`) — never logs or prints token values. (Spec §9)
- Cross-host archive selection must sort by the **filename** (`sort -t/ -k2`), never the full `host/filename` string — sorting the full string orders by hostname before timestamp, which is wrong. (Spec §4.2, caught in spec self-review)

Reference spec: `docs/superpowers/specs/2026-07-28-restore-hermes-hardening-design.md`

---

### Task 1: Cross-host auto-select (`resolve_cross_host_remote`)

**Files:**
- Modify: `restore-hermes.sh` (replace `prompt_for_remote_dir()` function and its call site)
- Test: `tests/restore-hermes.test.sh` (add test + fakebin helper)

**Interfaces:**
- Consumes: `$BASE_REMOTE`, `$ASSUME_YES`, `$DEFAULT_REMOTE`, `latest_archive_in_remote()`, `err()`, `log()` — all already exist in this file.
- Produces: `resolve_cross_host_remote()` — prints `"<remote-dir> <archive-name>"` (space-separated) on stdout on success, prints nothing and returns 1 if no archives exist anywhere. Replaces `prompt_for_remote_dir()` (which printed only `"<remote-dir>"`, leaving the caller to look up its latest archive separately).

- [ ] **Step 1: Write the failing test**

Append to `tests/restore-hermes.test.sh`, inserting this new helper + test function **before** the existing `test_auto_same_host_restore` / `test_prompt_cross_host_restore` calls at the bottom of the file:

```bash
mk_fakebin_cross_host_auto_select() {
  local fakebin="$1"
  cat >"$fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
echo "hermes import called: $*" >>"$TEST_LOG"
exit 0
EOF

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"enable --now hermes-backup.timer"* ]]; then
  echo "systemctl enable hermes-backup.timer called: $*" >>"$TEST_LOG"
fi
exit 0
EOF

  cat >"$fakebin/rclone" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/test-host" ]]; then
  exit 0
fi
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/" && "$3" == "-R" ]]; then
  printf 'aaa-newhost/hermes-20260720T030000Z.zip\nzzz-oldhost/hermes-20260701T030000Z.zip\n'
  exit 0
fi
if [[ "$1" == "copyto" ]]; then
  echo "rclone copyto called: $*" >>"$TEST_LOG"
  dst="$4"
  mkdir -p "$(dirname "$dst")"
  : >"$dst"
  exit 0
fi
if [[ "$1" == "listremotes" ]]; then
  echo "gdrive:"
  exit 0
fi
exit 0
EOF

  chmod +x "$fakebin/hermes" "$fakebin/systemctl" "$fakebin/rclone"
}

test_cross_host_auto_selects_most_recent_regardless_of_hostname() {
  local tmp output rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_cross_host_auto_select "$tmp"

  set +e
  output="$(PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "auto-selected most recent cross-host backup: gdrive:hermes-backups/aaa-newhost/hermes-20260720T030000Z.zip"
  assert_contains "$(cat "$TEST_LOG")" "rclone copyto called: copyto gdrive:hermes-backups/aaa-newhost/hermes-20260720T030000Z.zip"
  assert_contains "$(cat "$TEST_LOG")" "hermes import called"
}
```

And add the call right before `test_auto_same_host_restore`:

```bash
test_cross_host_auto_selects_most_recent_regardless_of_hostname
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/restore-hermes.test.sh`
Expected: FAIL — `ASSERT FAILED: expected output to contain: auto-selected most recent cross-host backup: ...` (the `aaa-newhost` archive is chronologically newest, but today's `prompt_for_remote_dir()` doesn't auto-select anything at all — it prompts on stderr and blocks on `read`, which will fail/hang against the test's non-interactive stdin).

- [ ] **Step 3: Replace `prompt_for_remote_dir()` with `resolve_cross_host_remote()`**

In `restore-hermes.sh`, find this exact function (lines 57-86):

```bash
prompt_for_remote_dir() {
  local dirs
  mapfile -t dirs < <(rclone lsf "$BASE_REMOTE/" --dirs-only 2>/dev/null | sed 's:/$::')
  if ((${#dirs[@]} == 0)); then
    return 1
  fi

  err "No backup found for current hostname path ($DEFAULT_REMOTE)."
  err "Select backup source:"
  local i=1
  for d in "${dirs[@]}"; do
    err "  [$i] $BASE_REMOTE/$d"
    i=$((i + 1))
  done

  printf "Enter selection number: " >&2
  read -r selection
  if ! [[ "$selection" =~ ^[0-9]+$ ]]; then
    err "invalid selection"
    exit 1
  fi

  local idx=$((selection - 1))
  if ((idx < 0 || idx >= ${#dirs[@]})); then
    err "selection out of range"
    exit 1
  fi

  printf '%s/%s\n' "$BASE_REMOTE" "${dirs[$idx]}"
}
```

Replace it with:

```bash
resolve_cross_host_remote() {
  local all_archives
  all_archives="$(rclone lsf "$BASE_REMOTE/" -R --files-only 2>/dev/null | grep -E '^[^/]+/hermes-.*\.zip$' | sort -t/ -k2)"
  if [[ -z "$all_archives" ]]; then
    return 1
  fi

  if ((ASSUME_YES == 1)) || ! (: </dev/tty) 2>/dev/null; then
    local newest host_dir archive
    newest="$(printf '%s\n' "$all_archives" | tail -n 1)"
    host_dir="${newest%%/*}"
    archive="${newest#*/}"
    log "auto-selected most recent cross-host backup: $BASE_REMOTE/$host_dir/$archive"
    printf '%s/%s %s\n' "$BASE_REMOTE" "$host_dir" "$archive"
    return 0
  fi

  local dirs
  mapfile -t dirs < <(rclone lsf "$BASE_REMOTE/" --dirs-only 2>/dev/null | sed 's:/$::')
  if ((${#dirs[@]} == 0)); then
    return 1
  fi

  err "No backup found for current hostname path ($DEFAULT_REMOTE)."
  err "Select backup source:"
  local i=1
  for d in "${dirs[@]}"; do
    err "  [$i] $BASE_REMOTE/$d"
    i=$((i + 1))
  done

  printf "Enter selection number: " >/dev/tty
  local selection
  read -r selection </dev/tty
  if ! [[ "$selection" =~ ^[0-9]+$ ]]; then
    err "invalid selection"
    exit 1
  fi

  local idx=$((selection - 1))
  if ((idx < 0 || idx >= ${#dirs[@]})); then
    err "selection out of range"
    exit 1
  fi

  local chosen_dir="$BASE_REMOTE/${dirs[$idx]}"
  local chosen_archive
  chosen_archive="$(latest_archive_in_remote "$chosen_dir")"
  printf '%s %s\n' "$chosen_dir" "$chosen_archive"
}
```

Then find the call site (lines 135-141):

```bash
if [[ -z "$ARCHIVE" && "$REMOTE" == "$DEFAULT_REMOTE" ]]; then
  selected_remote="$(prompt_for_remote_dir || true)"
  if [[ -n "$selected_remote" ]]; then
    REMOTE="$selected_remote"
    ARCHIVE="$(latest_archive_in_remote "$REMOTE")"
  fi
fi
```

Replace it with:

```bash
if [[ -z "$ARCHIVE" && "$REMOTE" == "$DEFAULT_REMOTE" ]]; then
  selected="$(resolve_cross_host_remote || true)"
  if [[ -n "$selected" ]]; then
    REMOTE="${selected% *}"
    ARCHIVE="${selected##* }"
  fi
fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/restore-hermes.test.sh`
Expected: `PASS: restore-hermes contract tests`

> **Discovered during execution:** two real bugs surfaced by running the
> *full* test file, not just the new test.
>
> 1. `resolve_cross_host_remote()`'s stdout is a return-value channel
>    (captured by the caller via `$(...)`) — the informational
>    `"auto-selected..."` message must go through `err()` (stderr), not
>    `log()` (stdout), or it gets concatenated into the captured return
>    value. The original `prompt_for_remote_dir()` already used `err()` for
>    exactly this reason; match it.
> 2. The pre-existing `test_prompt_cross_host_restore` passed `--yes` *and*
>    expected the interactive host-picker prompt to still appear (true
>    under the old code, where `--yes` only gated the final confirmation).
>    Under the new code this is no longer valid: `--yes` now means
>    auto-select, never prompt — that's the fix, not a regression. Retire
>    `test_prompt_cross_host_restore()` and its `mk_fakebin_cross_host_prompt`
>    helper entirely (leave a comment explaining why, don't just delete
>    silently) rather than patching it to keep asserting the old, now-wrong
>    contract. Its coverage is superseded by
>    `test_cross_host_auto_selects_most_recent_regardless_of_hostname`
>    above plus the genuinely-interactive manual check in the Final
>    Verification Gate.

- [ ] **Step 5: Commit**

```bash
git add restore-hermes.sh tests/restore-hermes.test.sh
git commit -m "feat(restore-hermes): auto-select most recent cross-host backup"
```

---

### Task 2: Root-profile gateway reinstall (`maybe_install_root_gateway`)

**Files:**
- Modify: `restore-hermes.sh` (add new function + call it in main flow)
- Modify: `tests/restore-hermes.test.sh` (add `assert_not_contains` helper + 2 tests)

**Interfaces:**
- Consumes: `$HOME/.hermes/.env`, `log()` (already exists).
- Produces: `maybe_install_root_gateway()` — no return value used; runs `hermes gateway install` as a side effect when a messaging token is present in `.env`, silent no-op otherwise.

- [ ] **Step 1: Write the failing tests**

Add this helper right after the existing `assert_contains` function definition near the top of `tests/restore-hermes.test.sh`:

```bash
assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output NOT to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}
```

Then append this helper + the two test functions, again before the final block of `test_*` calls:

```bash
mk_fakebin_for_gateway_tests() {
  local fakebin="$1"
  cat >"$fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
echo "hermes called: $*" >>"$TEST_LOG"
exit 0
EOF

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

  cat >"$fakebin/rclone" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "lsf" && "$2" == "gdrive:hermes-backups/test-host" ]]; then
  printf 'hermes-20260711T010000Z.zip\n'
  exit 0
fi
if [[ "$1" == "copyto" ]]; then
  dst="$4"
  mkdir -p "$(dirname "$dst")"
  : >"$dst"
  exit 0
fi
if [[ "$1" == "listremotes" ]]; then
  echo "gdrive:"
  exit 0
fi
exit 0
EOF

  chmod +x "$fakebin/hermes" "$fakebin/systemctl" "$fakebin/rclone"
}

test_root_gateway_installed_when_messaging_token_present() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_for_gateway_tests "$tmp"
  mkdir -p "$tmp/home/.hermes"
  printf 'TELEGRAM_BOT_TOKEN=123456:abcdefghijklmnopqrstuvwxyz0123456789\n' >"$tmp/home/.hermes/.env"

  PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes >/dev/null 2>&1

  assert_contains "$(cat "$TEST_LOG")" "hermes called: gateway install"
}

test_root_gateway_skipped_when_no_messaging_token() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  export TEST_LOG="$tmp/log"
  : >"$TEST_LOG"

  mk_fakebin_for_gateway_tests "$tmp"
  mkdir -p "$tmp/home/.hermes"
  printf 'SOME_OTHER_VAR=value\n' >"$tmp/home/.hermes/.env"

  PATH="$tmp:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes >/dev/null 2>&1

  assert_not_contains "$(cat "$TEST_LOG")" "gateway install"
}
```

And add both calls before the final `printf`/`echo` PASS line:

```bash
test_root_gateway_installed_when_messaging_token_present
test_root_gateway_skipped_when_no_messaging_token
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/restore-hermes.test.sh`
Expected: FAIL — `ASSERT FAILED: expected output to contain: hermes called: gateway install` (function doesn't exist yet, nothing calls `hermes gateway install`).

- [ ] **Step 3: Add `maybe_install_root_gateway()` and call it**

In `restore-hermes.sh`, add this function right after `enable_backup_timer()` (i.e., after its closing `}` and before `latest_archive_in_remote()`):

```bash
maybe_install_root_gateway() {
  # Mirrors install.sh's own messaging-token check (maybe_start_gateway(),
  # same exact var list) so a restored root/default profile gets its
  # gateway reinstalled automatically — hermes import itself only reminds
  # about *named* profiles, never the root one.
  local env_file="$HOME/.hermes/.env"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  local var val
  for var in TELEGRAM_BOT_TOKEN DISCORD_BOT_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN WHATSAPP_ENABLED; do
    val="$(grep "^${var}=" "$env_file" 2>/dev/null | cut -d'=' -f2-)"
    if [[ -n "$val" && "$val" != "your-token-here" ]]; then
      log "messaging token detected ($var); installing root gateway service"
      hermes gateway install || log "hermes gateway install failed; run it manually: hermes gateway install"
      return 0
    fi
  done
}
```

Then find the end of the main flow:

```bash
hermes import "$LOCAL_ARCHIVE" --force
enable_backup_timer
log "restore complete"
```

Replace it with:

```bash
hermes import "$LOCAL_ARCHIVE" --force
enable_backup_timer
maybe_install_root_gateway
log "restore complete"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/restore-hermes.test.sh`
Expected: `PASS: restore-hermes contract tests`

- [ ] **Step 5: Commit**

```bash
git add restore-hermes.sh tests/restore-hermes.test.sh
git commit -m "feat(restore-hermes): auto-reinstall root profile gateway when a messaging token is restored"
```

---

### Task 3: Offer to configure gdrive (`offer_rclone_config`)

**Files:**
- Modify: `restore-hermes.sh` (add new function, replace inline not-configured check)
- Test: `tests/restore-hermes.test.sh` (add 1 test)

**Interfaces:**
- Consumes: `$ASSUME_YES` (already exists).
- Produces: `offer_rclone_config()` — returns normally (script continues) if gdrive is/becomes configured; calls `exit 0` with the existing print-instructions message otherwise. Only the non-interactive fallback path is automated-tested (see Global Constraints) — the "offer, user says yes, run rclone config" path is manual-only (Final Verification Gate).

- [ ] **Step 1: Write the failing test**

Append to `tests/restore-hermes.test.sh`, before the final calls block:

```bash
test_gdrive_not_configured_yes_flag_exits_cleanly() {
  local tmp output rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/fakebin"
  cat >"$tmp/fakebin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$tmp/fakebin/rclone" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "listremotes" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$tmp/fakebin/hermes" "$tmp/fakebin/rclone"

  set +e
  output="$(PATH="$tmp/fakebin:$PATH" HOME="$tmp/home" HOSTNAME=test-host "$SUT" --yes 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  assert_contains "$output" "gdrive remote not configured; skipping restore"
}
```

And add the call before the final `printf`/`echo` PASS line:

```bash
test_gdrive_not_configured_yes_flag_exits_cleanly
```

- [ ] **Step 2: Run test to verify it already passes (regression lock-in, not a red step)**

Run: `bash tests/restore-hermes.test.sh`
Expected: `PASS: restore-hermes contract tests`. Unlike every other test in this plan, this one is **not** supposed to fail here — today's existing inline check already produces this exact message and exits 0. This step exists purely to lock in today's behavior as a checkpoint *before* refactoring the inline check into `offer_rclone_config()` in Step 3, so that Step 4 re-running the same test proves the refactor preserved it exactly.

- [ ] **Step 3: Replace the inline check with `offer_rclone_config()`**

In `restore-hermes.sh`, add this function right after `require_cmd()` (before `enable_backup_timer()`):

```bash
offer_rclone_config() {
  if rclone listremotes 2>/dev/null | grep -qx 'gdrive:'; then
    return 0
  fi

  if ((ASSUME_YES == 1)) || ! (: </dev/tty) 2>/dev/null; then
    err "gdrive remote not configured; skipping restore"
    err "run: rclone config && rclone lsd gdrive:"
    exit 0
  fi

  printf "gdrive remote not configured. Run 'rclone config' now to set it up? [Y/n] " >/dev/tty
  local answer
  read -r answer </dev/tty
  if [[ -n "$answer" && ! "$answer" =~ ^[Yy] ]]; then
    err "gdrive remote not configured; skipping restore"
    err "run: rclone config && rclone lsd gdrive:"
    exit 0
  fi

  rclone config </dev/tty >/dev/tty 2>&1 || true

  if ! rclone listremotes 2>/dev/null | grep -qx 'gdrive:'; then
    err "gdrive still not configured; skipping restore"
    err "run: rclone config && rclone lsd gdrive:"
    exit 0
  fi
}
```

Then find this exact block:

```bash
require_cmd hermes
require_cmd rclone

if ! rclone listremotes 2>/dev/null | grep -qx 'gdrive:'; then
  err "gdrive remote not configured; skipping restore"
  err "run: rclone config && rclone lsd gdrive:"
  exit 0
fi
```

Replace it with:

```bash
require_cmd hermes
require_cmd rclone

offer_rclone_config
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/restore-hermes.test.sh`
Expected: `PASS: restore-hermes contract tests` — confirms the refactor preserved the exact fallback message and exit-0 behavior.

- [ ] **Step 5: Commit**

```bash
git add restore-hermes.sh tests/restore-hermes.test.sh
git commit -m "feat(restore-hermes): offer to run rclone config interactively when unconfigured"
```

---

### Task 4: `NEW-LAPTOP.md` runbook + README link

**Files:**
- Create: `NEW-LAPTOP.md`
- Modify: `README.md` (add link in the existing "Hermes backup (Google Drive)" section)
- Test: `tests/docs-new-laptop.test.sh`

**Interfaces:**
- Consumes: nothing (pure documentation).
- Produces: `NEW-LAPTOP.md` at repo root; a link to it from `README.md`, matching the existing `TAILSCALE.md` pattern.

- [ ] **Step 1: Write the failing test**

Create `tests/docs-new-laptop.test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ -f "$ROOT_DIR/NEW-LAPTOP.md" ]] || {
  echo "FAIL: NEW-LAPTOP.md missing"
  exit 1
}

CONTENT="$(cat "$ROOT_DIR/NEW-LAPTOP.md")"

[[ "$CONTENT" == *"rclone config"* ]] || {
  echo "FAIL: NEW-LAPTOP.md missing rclone config step"
  exit 1
}

[[ "$CONTENT" == *"rclone authorize"* ]] || {
  echo "FAIL: NEW-LAPTOP.md missing headless/no-browser fallback"
  exit 1
}

[[ "$CONTENT" == *"by design"* ]] || {
  echo "FAIL: NEW-LAPTOP.md missing config.yaml/SOUL.md by-design note"
  exit 1
}

README_CONTENT="$(cat "$ROOT_DIR/README.md")"

[[ "$README_CONTENT" == *"[NEW-LAPTOP.md](NEW-LAPTOP.md)"* ]] || {
  echo "FAIL: README missing link to NEW-LAPTOP.md"
  exit 1
}

echo "PASS: new-laptop docs contract checks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/docs-new-laptop.test.sh`
Expected: FAIL — `FAIL: NEW-LAPTOP.md missing`

- [ ] **Step 3: Write `NEW-LAPTOP.md` and link it from `README.md`**

Create `NEW-LAPTOP.md`:

```markdown
# New Laptop Checklist

Steps to fully restore Hermes (and this machine's other automation) on a
brand-new laptop, in order.

## 1. Clone repos and run setup

Follow the main [README.md](README.md) bootstrap flow — `clone-repos.sh`,
then `endeavouros-setup.sh`. This installs Hermes fresh, but on a genuinely
new machine there's nothing to restore from yet (see step 2).

## 2. Configure Google Drive access (manual, every new machine)

This is the one step that can never be automated: `rclone` needs your
explicit OAuth consent to access Google Drive, and that consent has to
happen at least once per machine.

```sh
rclone config
rclone lsd gdrive:
```

`restore-hermes.sh` now offers to run `rclone config` for you interactively
if it detects gdrive isn't set up yet (and a real terminal is available) —
but you can also just run the two lines above yourself before re-running
`~/Proj/linux-setup/restore-hermes.sh`.

**No browser on this machine?** Use rclone's remote-authorize flow: run
`rclone authorize "drive"` on a machine that *does* have a browser (any
machine with rclone installed works, it doesn't need to be part of this
setup), complete the OAuth flow there, then paste the resulting token back
into `rclone config` on the new laptop when it asks for it.

## 3. Restore

```sh
~/Proj/linux-setup/restore-hermes.sh
```

If this laptop's hostname doesn't match any previous backup folder, you'll
be prompted to pick which host's backup to restore from (interactively), or
— if run with `--yes` / no terminal attached — it auto-picks the single
most recent backup across all hosts.

This also auto-reinstalls the gateway service (`hermes gateway install`) if
the restored `.env` has any messaging platform token configured.

## What's backed up vs. what isn't

**Backed up** (full Hermes backup, not `--quick`): `.env` (all API keys),
`auth.json` (provider credentials), `mcp-tokens/*` (MCP OAuth tokens),
`state.db` and every other DB, `cron/`, `kanban.db`, sessions, memories,
agent-created skills.

**Not backed up, by design — not a bug:**
- `~/.hermes/hermes-agent` (the agent code itself) — reinstalled fresh via
  the official installer (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`,
  run by `hermes-setup.sh`), not restored from a zip. Code isn't state.
- `config.yaml` and `SOUL.md` — these are symlinks on this host
  (`config.yaml -> ../dotfiles/hermes/.hermes/config.yaml`,
  `SOUL.md -> ~/Proj/agent-lib/providers/hermes/SOUL.md`), and Hermes's own
  backup skips symlinks unconditionally. They're recreated independently by
  dotfiles-stow and `agent-lib/install.sh` during the normal bootstrap flow
  (step 1), not by `hermes import`. If you ever see these "missing" from a
  restored backup, that's expected — don't go looking for a bug here.
- `~/.config/rclone/rclone.conf` — see step 2. Can't be included in the
  Hermes backup (it lives outside `~/.hermes`) and can't be bootstrapped
  from Drive either, since it's the credential that gates access to Drive
  in the first place.

## After restore

- Named Hermes profiles: `hermes import` itself prints a reminder —
  `hermes -p <profile> gateway install` for each one that needs it.
- Root/default profile: handled automatically by `restore-hermes.sh` (see
  step 3) if a messaging token is present.
- If `hermes-agent` somehow ended up missing post-restore, `hermes import`
  itself will tell you to run `hermes update`.
```

In `README.md`, find this exact text (end of the "Hermes backup (Google Drive)" section):

```
`restore-hermes.sh` restores the latest archive and enables the backup timer
automatically.

Idempotent. Re-run safe.
```

Replace it with:

```
`restore-hermes.sh` restores the latest archive and enables the backup timer
automatically.

Idempotent. Re-run safe.

Full new-laptop restore runbook: [NEW-LAPTOP.md](NEW-LAPTOP.md)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/docs-new-laptop.test.sh`
Expected: `PASS: new-laptop docs contract checks`

- [ ] **Step 5: Commit**

```bash
git add NEW-LAPTOP.md README.md tests/docs-new-laptop.test.sh
git commit -m "docs: add new-laptop restore runbook"
```

---

## Final Verification Gate

- [ ] Run the full new/modified test set:

```bash
bash tests/restore-hermes.test.sh && \
bash tests/docs-new-laptop.test.sh
```

Expected: both `PASS:` lines, exit code 0.

- [ ] Run the full existing repo test set to confirm nothing else broke:

```bash
for f in tests/*.test.sh; do bash "$f" || echo "FAILED: $f"; done
```

Expected: every file prints its own `PASS:` line; no `FAILED:` lines.

- [ ] Shell syntax check:

```bash
bash -n restore-hermes.sh
```

Expected: no output, exit code 0.

- [ ] Manual check 1 — the interactive `rclone config` offer (real terminal, real `rclone`):

```bash
rclone config disconnect gdrive:   # or otherwise temporarily unconfigure gdrive
./restore-hermes.sh
```

Expected: prompted `"gdrive remote not configured. Run 'rclone config' now to set it up? [Y/n]"`; answering yes launches the real interactive `rclone config` wizard attached to the terminal. Re-run `rclone config` afterward (or restore from a saved copy of `rclone.conf`) to leave the real gdrive remote working again.

- [ ] Manual check 2 — the interactive host picker (real terminal):

```bash
./restore-hermes.sh --remote gdrive:hermes-backups/nonexistent-host-xyz
```

Expected: `DEFAULT_REMOTE` won't match, falls into `resolve_cross_host_remote()`; since this is a real terminal (not `--yes`), confirm the numbered host list appears and prompts for a selection rather than auto-selecting.
