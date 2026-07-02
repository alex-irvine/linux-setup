# Remote tmux via Tailscale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure, low-friction mobile access to host tmux sessions by wiring Tailscale + SSH setup into `linux-setup` and adding tmux convenience helpers in `dotfiles`.

**Architecture:** `linux-setup` owns installation/bootstrap and operator runbooks, while `dotfiles` owns day-2 shell ergonomics. Access path is private tailnet SSH, not public relay. Scripts are idempotent, fail clearly, and print exact next actions for manual auth steps.

**Tech Stack:** Bash, systemd, pacman, Tailscale CLI, OpenSSH/Tailscale SSH, zsh, tmux, Markdown docs

## Global Constraints

- Primary implementation target: `linux-setup`; secondary target: `dotfiles`.
- No Muxile code changes in v1.
- Mobile requirements must be documented, not scripted.
- Preferred auth posture: Tailscale SSH policy-managed access; fallback: OpenSSH over tailnet with key-based auth only.
- Do not expose terminal endpoints publicly for this v1 path.
- Script changes must be idempotent and safe on rerun.

---

## File Map

### `linux-setup` repository

- Create: `tests/setup-tailscale.test.sh` - contract tests for `setup-tailscale.sh` using command stubs.
- Create: `tests/endeavouros-tailscale-wireup.test.sh` - verifies package install + setup invocation wiring.
- Create: `tests/docs-tailscale.test.sh` - validates required doc sections and mobile requirements.
- Create: `setup-tailscale.sh` - idempotent tailscaled/auth/status bootstrap script.
- Create: `TAILSCALE.md` - runbook: setup, mobile apps, usage, troubleshooting, lost device response.
- Modify: `endeavouros-setup.sh` - install Tailscale package and call `setup-tailscale.sh`.
- Modify: `README.md` - add "Remote tmux via Tailscale" entrypoint and links.

### `dotfiles` repository

- Create: `zsh/.config/zsh/tmux-helpers.zsh` - shell functions for tmux list/attach/create-or-attach.
- Create: `zsh/tests/tmux-helpers.test.sh` - tests for helper behavior with stubbed `tmux` command.
- Modify: `zsh/.zshrc` - source helper file.
- Modify: `README.md` - document helper usage.

## Contracts and Interfaces

- `linux-setup/setup-tailscale.sh` CLI contract:
  - `setup-tailscale.sh`
  - Exit `0`: daemon running + auth present.
  - Exit `10`: manual login required (not a hard error).
  - Exit `1`: hard failure (missing commands, daemon start failure).
- `setup-tailscale.sh` function interfaces:
  - `require_cmd() -> 0|1`
  - `ensure_tailscaled_active() -> 0|1`
  - `tailscale_login_state() -> "logged_in"|"logged_out"`
  - `print_login_next_step() -> stdout text`
  - `print_status_summary() -> stdout text`
- `dotfiles` helper interfaces:
  - `tmxls()`: runs `tmux ls`.
  - `tmxa <session>`: runs `tmux attach -t <session>`.
  - `tmxw [session=work]`: create-if-missing + attach.

### Task 1: Create failing contract tests and minimal `setup-tailscale.sh`

**Files:**
- Create: `tests/setup-tailscale.test.sh`
- Create: `setup-tailscale.sh`

**Interfaces:**
- Consumes: none
- Produces: `setup-tailscale.sh` base contract and first passing test (`missing tailscale binary -> exit 1`)

- [ ] **Step 1: Write the failing test**

```bash
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/setup-tailscale.test.sh`
Expected: FAIL with `No such file or directory` for `setup-tailscale.sh`.

- [ ] **Step 3: Write minimal implementation**

```bash
#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[tailscale] missing required command: $cmd"
    return 1
  fi
}

main() {
  require_cmd tailscale || exit 1
  require_cmd systemctl || exit 1
  echo "[tailscale] prerequisites OK"
}

main "$@"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/setup-tailscale.test.sh`
Expected: `PASS: setup-tailscale contract test (missing binary)`.

- [ ] **Step 5: Commit**

```bash
git -C /home/alex/Proj/linux-setup add tests/setup-tailscale.test.sh setup-tailscale.sh
git -C /home/alex/Proj/linux-setup commit -m "test: add initial setup-tailscale contract"
```

### Task 2: Implement daemon/auth/status logic in `setup-tailscale.sh`

**Files:**
- Modify: `tests/setup-tailscale.test.sh`
- Modify: `setup-tailscale.sh`

**Interfaces:**
- Consumes: `setup-tailscale.sh` base CLI from Task 1
- Produces: stable script contract (`0` ready, `10` login required, `1` hard fail)

- [ ] **Step 1: Extend tests with failing auth and ready-state cases**

```bash
# Append these test functions to tests/setup-tailscale.test.sh

mk_stub_cmds_logged_out() {
  local fakebin="$1"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" ]]; then
  echo "Logged out."
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
if [[ "$1" == "cert" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

mk_stub_cmds_logged_in() {
  local fakebin="$1"
  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "is-active" ]]; then
  exit 0
fi
exit 0
EOF
  cat >"$fakebin/tailscale" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "status" ]]; then
  echo "100.64.0.10  laptop  linux   active"
  exit 0
fi
if [[ "$1" == "ip" ]]; then
  echo "100.64.0.10"
  exit 0
fi
if [[ "$1" == "cert" ]]; then
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl" "$fakebin/tailscale"
}

test_logged_out_returns_10_and_prints_next_step() {
  local fakebin
  fakebin="$(mktemp -d)"
  mk_stub_cmds_logged_out "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 10 ]]
  assert_contains "$output" "[tailscale] login required"
  assert_contains "$output" "tailscale up --ssh"
}

test_logged_in_returns_0_and_prints_status() {
  local fakebin
  fakebin="$(mktemp -d)"
  mk_stub_cmds_logged_in "$fakebin"

  set +e
  local output
  output="$(PATH="$fakebin" "$SUT" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 0 ]]
  assert_contains "$output" "[tailscale] ready"
  assert_contains "$output" "100.64.0.10"
}

test_logged_out_returns_10_and_prints_next_step
test_logged_in_returns_0_and_prints_status
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/setup-tailscale.test.sh`
Expected: FAIL because script does not yet emit `login required`, `ready`, or exit `10` on logged-out state.

- [ ] **Step 3: Implement minimal logic to satisfy contract**

```bash
#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[tailscale] missing required command: $cmd"
    return 1
  fi
}

ensure_tailscaled_active() {
  if systemctl is-active --quiet tailscaled; then
    return 0
  fi

  echo "[tailscale] tailscaled inactive; starting service"
  if ! sudo systemctl enable --now tailscaled >/dev/null 2>&1; then
    echo "[tailscale] failed to start tailscaled"
    echo "[tailscale] debug: sudo journalctl -u tailscaled --no-pager -n 50"
    return 1
  fi
}

tailscale_login_state() {
  local status_out
  status_out="$(tailscale status 2>&1 || true)"
  if [[ "$status_out" == *"Logged out"* ]]; then
    echo "logged_out"
  else
    echo "logged_in"
  fi
}

print_login_next_step() {
  echo "[tailscale] login required"
  echo "[tailscale] next: sudo tailscale up --ssh"
}

print_status_summary() {
  local ip
  ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  echo "[tailscale] ready"
  if [[ -n "$ip" ]]; then
    echo "[tailscale] ipv4: $ip"
  fi
}

main() {
  require_cmd tailscale || exit 1
  require_cmd systemctl || exit 1
  ensure_tailscaled_active || exit 1

  if [[ "$(tailscale_login_state)" == "logged_out" ]]; then
    print_login_next_step
    exit 10
  fi

  print_status_summary
}

main "$@"
```

- [ ] **Step 4: Run tests and syntax checks**

Run: `bash tests/setup-tailscale.test.sh && bash -n setup-tailscale.sh`
Expected: test script prints `PASS` and `bash -n` produces no output.

- [ ] **Step 5: Commit**

```bash
git -C /home/alex/Proj/linux-setup add tests/setup-tailscale.test.sh setup-tailscale.sh
git -C /home/alex/Proj/linux-setup commit -m "feat: implement tailscale setup auth and status flow"
```

### Task 3: Wire Tailscale into `endeavouros-setup.sh`

**Files:**
- Create: `tests/endeavouros-tailscale-wireup.test.sh`
- Modify: `endeavouros-setup.sh`

**Interfaces:**
- Consumes: `setup-tailscale.sh` from Task 2
- Produces: main bootstrap flow installs package and calls setup script

- [ ] **Step 1: Write failing integration test for script wiring**

```bash
#!/usr/bin/env bash
set -euo pipefail

FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *"tailscale"* ]] || { echo "FAIL: tailscale package install missing"; exit 1; }
[[ "$CONTENT" == *"setup-tailscale.sh"* ]] || { echo "FAIL: setup-tailscale.sh call missing"; exit 1; }

echo "PASS: tailscale wireup present"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/endeavouros-tailscale-wireup.test.sh`
Expected: FAIL with missing tailscale package install and/or setup call.

- [ ] **Step 3: Modify `endeavouros-setup.sh` with minimal wireup**

```bash
# Add tailscale package to the base tools install block
sudo pacman -S --noconfirm --needed \
  base-devel curl wget gnupg ca-certificates unzip clang pkgconf git github-cli \
  git-delta tailscale

# Add this near existing setup helper invocations (before final completion)
echo "==== Running setup-tailscale.sh ===="
bash "$SCRIPT_DIR/setup-tailscale.sh" || {
  rc=$?
  if [ "$rc" -eq 10 ]; then
    echo "==== Tailscale manual login required; re-run setup-tailscale.sh after login ===="
  else
    exit "$rc"
  fi
}
```

- [ ] **Step 4: Run integration and syntax checks**

Run: `bash tests/endeavouros-tailscale-wireup.test.sh && bash -n endeavouros-setup.sh`
Expected: `PASS: tailscale wireup present` and no syntax errors.

- [ ] **Step 5: Commit**

```bash
git -C /home/alex/Proj/linux-setup add tests/endeavouros-tailscale-wireup.test.sh endeavouros-setup.sh
git -C /home/alex/Proj/linux-setup commit -m "feat: wire tailscale setup into bootstrap"
```

### Task 4: Add Tailscale runbook and README entrypoint

**Files:**
- Create: `tests/docs-tailscale.test.sh`
- Create: `TAILSCALE.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: setup behavior from Tasks 2-3
- Produces: user-facing setup/usage/troubleshooting docs including mobile app requirements

- [ ] **Step 1: Write failing docs contract test**

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAIL_DOC="$ROOT_DIR/TAILSCALE.md"
README="$ROOT_DIR/README.md"

[[ -f "$TAIL_DOC" ]] || { echo "FAIL: missing TAILSCALE.md"; exit 1; }

TAIL_CONTENT="$(cat "$TAIL_DOC")"
README_CONTENT="$(cat "$README")"

[[ "$TAIL_CONTENT" == *"## Mobile apps (manual install)"* ]] || { echo "FAIL: missing mobile apps section"; exit 1; }
[[ "$TAIL_CONTENT" == *"Tailscale"* ]] || { echo "FAIL: missing Tailscale app mention"; exit 1; }
[[ "$TAIL_CONTENT" == *"SSH"* ]] || { echo "FAIL: missing SSH app mention"; exit 1; }
[[ "$TAIL_CONTENT" == *"## Lost device response"* ]] || { echo "FAIL: missing lost-device section"; exit 1; }
[[ "$README_CONTENT" == *"Remote tmux via Tailscale"* ]] || { echo "FAIL: README missing remote tmux section"; exit 1; }
[[ "$README_CONTENT" == *"TAILSCALE.md"* ]] || { echo "FAIL: README missing TAILSCALE.md link"; exit 1; }

echo "PASS: docs contract checks"
```

- [ ] **Step 2: Run docs test to verify it fails**

Run: `bash tests/docs-tailscale.test.sh`
Expected: FAIL because `TAILSCALE.md` and README section are not yet present.

- [ ] **Step 3: Write docs with exact required sections**

```markdown
<!-- TAILSCALE.md skeleton to create -->
# Tailscale Remote tmux

## What this gives you
- Private tailnet path to SSH into this host from mobile.
- Reuse existing local tmux sessions.

## Host setup
1. Run `bash setup-tailscale.sh`.
2. If prompted, run `sudo tailscale up --ssh`.
3. Verify with `tailscale status` and `tailscale ip -4`.

## Mobile apps (manual install)
- Install `Tailscale` app on iOS/Android.
- Install an SSH client app:
  - iOS: Termius or Blink Shell.
  - Android: Termius or JuiceSSH.

## First connect from phone
1. Connect phone to tailnet in Tailscale app.
2. SSH to host tailnet name/IP.
3. Run `tmux ls` then attach.

## Daily usage
- SSH in, run `tmxw` (or `tmux attach -t work`).

## Troubleshooting
- If `tailscaled` not active: `sudo systemctl status tailscaled`.
- If login missing: `sudo tailscale up --ssh`.
- If connection is slow: likely relay path; test another network.

## Lost device response
1. Remove compromised phone from Tailscale admin/devices.
2. Rotate SSH keys if using OpenSSH fallback.
3. Re-authenticate trusted devices.
```

```markdown
<!-- README.md section to add -->
## Remote tmux via Tailscale

Use Tailscale + SSH to attach to running tmux sessions from mobile without exposing public terminal endpoints.

- Host setup and troubleshooting: `TAILSCALE.md`
- Mobile requirements are documented there (manual install).
```

- [ ] **Step 4: Run docs test**

Run: `bash tests/docs-tailscale.test.sh`
Expected: `PASS: docs contract checks`.

- [ ] **Step 5: Commit**

```bash
git -C /home/alex/Proj/linux-setup add tests/docs-tailscale.test.sh TAILSCALE.md README.md
git -C /home/alex/Proj/linux-setup commit -m "docs: add tailscale remote tmux runbook"
```

### Task 5: Add tmux helper functions in `dotfiles`

**Files:**
- Create: `zsh/tests/tmux-helpers.test.sh`
- Create: `zsh/.config/zsh/tmux-helpers.zsh`
- Modify: `zsh/.zshrc`
- Modify: `README.md`

**Interfaces:**
- Consumes: host has tmux available and remote shell access via SSH
- Produces: helper commands `tmxls`, `tmxa`, `tmxw`

- [ ] **Step 1: Write failing helper tests**

```bash
#!/usr/bin/env bash
set -euo pipefail

HELPERS_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.config/zsh/tmux-helpers.zsh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  [[ "$haystack" == *"$needle"* ]] || { echo "FAIL: expected '$needle'"; exit 1; }
}

test_tmxw_creates_and_attaches_when_missing() {
  local calls
  calls="$(mktemp)"

  tmux() {
    printf '%s\n' "$*" >>"$calls"
    if [[ "$1" == "has-session" ]]; then
      return 1
    fi
    return 0
  }

  # shellcheck disable=SC1090
  source "$HELPERS_FILE"
  tmxw work

  local out
  out="$(cat "$calls")"
  assert_contains "$out" "has-session -t work"
  assert_contains "$out" "new-session -d -s work"
  assert_contains "$out" "attach -t work"
}

test_tmxw_creates_and_attaches_when_missing
echo "PASS: tmux helper tests"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `bash zsh/tests/tmux-helpers.test.sh`
Expected: FAIL because helper file does not yet exist.

- [ ] **Step 3: Implement helper functions and source them in `.zshrc`**

```zsh
# zsh/.config/zsh/tmux-helpers.zsh
tmxls() {
  tmux ls
}

tmxa() {
  if [ -z "${1:-}" ]; then
    echo "usage: tmxa <session>"
    return 1
  fi
  tmux attach -t "$1"
}

tmxw() {
  local session="${1:-work}"
  if ! tmux has-session -t "$session" 2>/dev/null; then
    tmux new-session -d -s "$session"
  fi
  tmux attach -t "$session"
}
```

```zsh
# Add to zsh/.zshrc (once)
if [ -f "$HOME/.config/zsh/tmux-helpers.zsh" ]; then
  source "$HOME/.config/zsh/tmux-helpers.zsh"
fi
```

```markdown
<!-- Add to dotfiles README.md -->
## tmux remote helpers

- `tmxls` - list sessions
- `tmxa <session>` - attach existing session
- `tmxw [session]` - create if missing, then attach (default: `work`)
```

- [ ] **Step 4: Run helper tests and zsh syntax check**

Run: `bash zsh/tests/tmux-helpers.test.sh && zsh -n zsh/.zshrc`
Expected: `PASS: tmux helper tests` and no `zsh -n` errors.

- [ ] **Step 5: Commit**

```bash
git -C /home/alex/dotfiles add zsh/tests/tmux-helpers.test.sh zsh/.config/zsh/tmux-helpers.zsh zsh/.zshrc README.md
git -C /home/alex/dotfiles commit -m "feat: add tmux remote helper commands"
```

### Task 6: End-to-end verification and rollout notes

**Files:**
- Modify: `TAILSCALE.md`
- Modify: `README.md` (linux-setup and dotfiles only if verification notes missing)

**Interfaces:**
- Consumes: all previous tasks
- Produces: verified operator flow and explicit rollout checklist

- [ ] **Step 1: Run linux-setup test suite and syntax checks**

Run: `bash tests/setup-tailscale.test.sh && bash tests/endeavouros-tailscale-wireup.test.sh && bash tests/docs-tailscale.test.sh && bash -n setup-tailscale.sh && bash -n endeavouros-setup.sh`
Expected: all tests print `PASS`; syntax checks silent.

- [ ] **Step 2: Run dotfiles helper checks**

Run: `bash zsh/tests/tmux-helpers.test.sh && zsh -n zsh/.zshrc`
Expected: `PASS: tmux helper tests`; no zsh syntax errors.

- [ ] **Step 3: Execute manual mobile smoke test and capture commands in docs**

```text
Manual smoke script:
1) On host: bash setup-tailscale.sh
2) On phone: connect tailnet in Tailscale app
3) On phone SSH client: ssh <host-tailnet-name>
4) In shell: tmxw work
5) Disconnect/reconnect and run: tmxw work
Expected: same tmux session resumes.
```

- [ ] **Step 4: Add verification log subsection to `TAILSCALE.md`**

```markdown
## Verification log template

- Date:
- Host:
- Phone OS/app:
- Tailnet path: direct or relay
- Result: pass/fail
- Notes:
```

- [ ] **Step 5: Commit verification updates**

```bash
git -C /home/alex/Proj/linux-setup add TAILSCALE.md README.md
git -C /home/alex/Proj/linux-setup commit -m "docs: add tailscale verification checklist"
```
