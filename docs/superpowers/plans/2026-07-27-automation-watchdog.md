# Automation Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One desktop notification, with the fix command already in the body, when a Hermes-cron job or this repo's systemd `--user` timer vanishes, fails, or goes stale — closing the blind spot that let `hermes-backup-gdrive` disappear silently on 2026-07-21.

**Architecture:** A single bash script (`automation-watchdog/automation-watchdog`) with embedded `python3` for JSON/snapshot logic, triggered by its own `systemd --user` timer every 4h, independent of the Hermes gateway. It checks two backends (Hermes-cron via `~/.hermes/cron/jobs.json`, systemd via `systemctl --user show`/hardcoded tracked-timer list), diffs against a small snapshot file to catch "vanished", and fires `notify-send` (reusing `alarm-trigger`'s session-discovery code) with a concrete fix command per problem. Silent exit 0 when healthy.

**Tech Stack:** bash (`set -euo pipefail`), inline `python3` heredocs (stdlib `json`/`datetime` only, no third-party deps), `systemd --user` units, `notify-send`/`libnotify`.

## Global Constraints

- Read-only / observer only: never mutates a Hermes-cron job or a systemd unit. Every problem is reported with a fix command; nothing is auto-healed. (Spec §3, §9)
- No new runtime dependencies: only `python3`, `systemctl --user`, `notify-send`, and the optional sound fallback chain (`paplay`/`pw-play`/`canberra-gtk-play`) — all already required by `alarm-cli` or `hermes-backup-gdrive.sh`. (Spec §6.1)
- Script + both systemd unit files are versioned directly in `linux-setup` (deliberate deviation from the `hermes-backup` precedent of `dotfiles`/`agent-lib` — this tool isn't Hermes-specific). (Spec §2)
- Reuse `alarm/alarm-trigger`'s `prepare_desktop_env()` verbatim for `XDG_RUNTIME_DIR`/`DBUS_SESSION_BUS_ADDRESS` discovery — do not reinvent it. (Spec §2, §4.1)
- Test files are standalone bash, no shared helper sourced across files (matches every existing file under `tests/` in this repo) — each test file defines its own `assert_*` functions inline. Fake external binaries (`systemctl`, `notify-send`) on `PATH` in a per-test `$fakebin`/`$tmp` dir; sandbox `$HOME` per test. No test may touch the real `~/.hermes` or real systemd user instance.
- Commit messages: lowercase, conventional-commits-style prefix (`feat`/`test`/`docs`), matching this repo's existing git log.
- Systemd timer for `automation-watchdog` itself uses `Persistent=true` (same catch-up-after-suspend pattern as `hermes-backup.timer`).

Reference spec: `docs/superpowers/specs/2026-07-27-automation-watchdog-design.md`

---

### Task 1: Hermes-cron backend detection

**Files:**
- Create: `automation-watchdog/automation-watchdog`
- Test: `tests/automation-watchdog.test.sh`

**Interfaces:**
- Consumes: `~/.hermes/cron/jobs.json` shape from hermes-agent's `cron/jobs.py` — each job dict has `id`, `name`, `enabled` (bool), `state` (`"scheduled"`/`"paused"`), `schedule` (dict with `kind` ∈ `"once"`/`"interval"`/`"minutes"`/`"cron"`+`"expr"`/`"display"`), `next_run_at` (ISO string or null), `last_run_at`, `last_status` (`"ok"`/`"error"`/null), `last_error`, `script`, `no_agent` (bool).
- Produces: `check_hermes_cron()` bash function — prints zero or more tab-separated lines `backend\tkind\tname\tfix` to stdout (`backend` always `hermes_cron`; `kind` ∈ `vanished`/`failing`/`stale`), exit status 0 normally, exit status 2 if `jobs.json` exists but is not valid JSON. Reads/writes `$SNAPSHOT_FILE`'s `hermes_cron` key (writes are skipped when `$DRY_RUN=1`).

- [ ] **Step 1: Write the failing test**

Create `tests/automation-watchdog.test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/automation-watchdog/automation-watchdog"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output NOT to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

write_jobs_file() {
  local home="$1" body="$2"
  mkdir -p "$home/.hermes/cron"
  printf '{"jobs": [%s], "updated_at": "2026-07-27T00:00:00+00:00"}' "$body" \
    >"$home/.hermes/cron/jobs.json"
}

write_snapshot() {
  local data_dir="$1" body="$2"
  mkdir -p "$data_dir"
  printf '%s' "$body" >"$data_dir/snapshot.json"
}

test_hermes_cron_job_vanished_reports_reconstructed_fix() {
  local tmp home data_dir output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {"job-1": {"name": "hermes-backup-gdrive", "schedule_display": "0 3 * * *", "script": "hermes-backup-gdrive.sh", "no_agent": true}}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_contains "$output" "hermes_cron"
  assert_contains "$output" "vanished"
  assert_contains "$output" 'hermes cron create "0 3 * * *" --name hermes-backup-gdrive --script hermes-backup-gdrive.sh --no-agent'
}

test_hermes_cron_job_failing_reports_last_error() {
  local tmp home data_dir output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"

  write_jobs_file "$home" '{"id": "job-2", "name": "nightly-report", "enabled": true, "state": "scheduled", "schedule": {"kind": "cron", "expr": "0 6 * * *", "display": "0 6 * * *"}, "next_run_at": "2026-07-27T06:00:00+00:00", "last_run_at": "2026-07-26T06:00:00+00:00", "last_status": "error", "last_error": "boom", "script": "nightly.sh", "no_agent": true}'
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_contains "$output" "failing"
  assert_contains "$output" "boom"
}

test_hermes_cron_job_stale_reports_last_run() {
  local tmp home data_dir output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"

  write_jobs_file "$home" '{"id": "job-3", "name": "old-report", "enabled": true, "state": "scheduled", "schedule": {"kind": "cron", "expr": "0 3 * * *", "display": "0 3 * * *"}, "next_run_at": "2026-07-01T03:00:00+00:00", "last_run_at": "2026-06-30T03:00:00+00:00", "last_status": "ok", "last_error": null, "script": "old.sh", "no_agent": true}'
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_contains "$output" "stale"
  assert_contains "$output" "old-report"
}

test_healthy_job_reports_nothing() {
  local tmp home data_dir future output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"
  future="$(date -u -d '+1 day' '+%Y-%m-%dT%H:%M:%S+00:00')"

  write_jobs_file "$home" "{\"id\": \"job-4\", \"name\": \"healthy-report\", \"enabled\": true, \"state\": \"scheduled\", \"schedule\": {\"kind\": \"cron\", \"expr\": \"0 3 * * *\", \"display\": \"0 3 * * *\"}, \"next_run_at\": \"$future\", \"last_run_at\": \"2026-07-27T03:00:00+00:00\", \"last_status\": \"ok\", \"last_error\": null, \"script\": \"healthy.sh\", \"no_agent\": true}"
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_not_contains "$output" "healthy-report"
}

test_hermes_cron_job_vanished_reports_reconstructed_fix
test_hermes_cron_job_failing_reports_last_error
test_hermes_cron_job_stale_reports_last_run
test_healthy_job_reports_nothing
printf 'PASS: automation-watchdog contract tests\n'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/automation-watchdog.test.sh`
Expected: FAIL — `bash: .../automation-watchdog/automation-watchdog: No such file or directory` (the script doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `automation-watchdog/automation-watchdog`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${WATCHDOG_DATA_DIR:-$HOME/.local/share/automation-watchdog}"
SNAPSHOT_FILE="$DATA_DIR/snapshot.json"
LOG_FILE="$DATA_DIR/watchdog.log"
JOBS_FILE="$HOME/.hermes/cron/jobs.json"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
  esac
done

check_hermes_cron() {
  python3 - "$JOBS_FILE" "$SNAPSHOT_FILE" "$DRY_RUN" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

jobs_file, snapshot_file, dry_run = sys.argv[1], sys.argv[2], sys.argv[3] == "1"


def load_jobs(path):
    if not os.path.exists(path):
        return {"jobs": []}
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"unreadable: {e}", file=sys.stderr)
        sys.exit(2)


def load_snapshot(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"hermes_cron": {}, "systemd": {}}


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def period_seconds_for(schedule):
    kind = schedule.get("kind")
    if kind == "interval":
        return int(schedule.get("minutes", 1440)) * 60
    if kind == "cron":
        # No croniter dependency in this system python3 — this repo only
        # ever schedules simple daily-at-HH:MM cron jobs, so treat any
        # "cron" kind as a daily period. Coarse but sufficient for a
        # "way overdue" staleness signal, not exact scheduling math.
        return 86400
    return None  # "once" (one-shot) jobs are excluded from staleness checks


def grace_seconds_for(period_seconds):
    if period_seconds is None:
        return 120
    return max(120, min(period_seconds // 2, 7200))


jobs_data = load_jobs(jobs_file)
jobs = jobs_data.get("jobs") or []
current_by_id = {j["id"]: j for j in jobs if isinstance(j, dict) and j.get("id")}

snapshot = load_snapshot(snapshot_file)
previous = snapshot.get("hermes_cron", {})

now = datetime.now(timezone.utc)
problems = []

for job_id, prev_job in previous.items():
    if job_id in current_by_id:
        continue
    name = prev_job.get("name", job_id)
    schedule_display = prev_job.get("schedule_display", "")
    script = prev_job.get("script")
    no_agent_flag = " --no-agent" if prev_job.get("no_agent") else ""
    script_part = f" --script {script}{no_agent_flag}" if script else ""
    fix = f'hermes cron create "{schedule_display}" --name {name}{script_part}'
    problems.append(("hermes_cron", "vanished", name, fix))

for job_id, job in current_by_id.items():
    if not job.get("enabled", True) or job.get("state") == "paused":
        continue

    name = job.get("name", job_id)

    if job.get("last_status") == "error":
        last_error = job.get("last_error") or "(no error text recorded)"
        script = job.get("script")
        debug_cmd = f"bash ~/.hermes/scripts/{script}" if script else "hermes cron list"
        problems.append((
            "hermes_cron", "failing", name,
            f"job '{name}' failing: {last_error}. Debug: {debug_cmd}",
        ))
        continue

    schedule = job.get("schedule") or {}
    period_seconds = period_seconds_for(schedule)
    if period_seconds is None:
        continue

    next_run_at = parse_iso(job.get("next_run_at"))
    if next_run_at is None:
        continue

    grace_seconds = grace_seconds_for(period_seconds)
    overdue_by = (now - next_run_at).total_seconds()
    if overdue_by > period_seconds + grace_seconds:
        problems.append((
            "hermes_cron", "stale", name,
            f"job '{name}' hasn't run since {job.get('last_run_at') or 'never'}, "
            f"expected every {schedule.get('display', 'its schedule')}. "
            f"Check: hermes cron list",
        ))

for line in problems:
    print("\t".join(line))

if not dry_run:
    new_snapshot = {
        "hermes_cron": {
            jid: {
                "name": j.get("name", jid),
                "schedule_display": j.get("schedule_display", j.get("schedule", {}).get("display", "")),
                "script": j.get("script"),
                "no_agent": j.get("no_agent", False),
            }
            for jid, j in current_by_id.items()
        },
        "systemd": snapshot.get("systemd", {}),
    }
    with open(snapshot_file, "w") as f:
        json.dump(new_snapshot, f, indent=2)
PY
}

main() {
  mkdir -p "$DATA_DIR"
  check_hermes_cron
}

main "$@"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/automation-watchdog.test.sh`
Expected: `PASS: automation-watchdog contract tests`

- [ ] **Step 5: Commit**

```bash
git add automation-watchdog/automation-watchdog tests/automation-watchdog.test.sh
git commit -m "feat(automation-watchdog): hermes-cron backend detection"
```

---

### Task 2: Systemd timer backend detection

**Files:**
- Modify: `automation-watchdog/automation-watchdog` (add `check_systemd_timers`, extend `main`)
- Modify: `tests/automation-watchdog.test.sh` (add 4 test functions)

**Interfaces:**
- Consumes: `systemctl --user show <unit> --property=<PROP> --value` (real properties confirmed live: `UnitFileState`, `ActiveState`, `Result`, `NextElapseUSecRealtime` — the latter two only apply to `.timer`/`.service` respectively as shown below).
- Produces: `check_systemd_timers()` bash function — same tab-separated `backend\tkind\tname\tfix` output contract as `check_hermes_cron` (`backend` always `systemd`), reading `TRACKED_TIMERS=(hermes-backup automation-watchdog)`. Exit status 1 if `systemctl --user` itself is unreachable (no problem lines printed in that case).

- [ ] **Step 1: Write the failing tests**

Append to `tests/automation-watchdog.test.sh`, inserting these 4 test functions and their fakebin helpers **before** the final block of `test_*` calls + `printf 'PASS...'` line (so they run alongside the existing 4):

```bash
mk_fake_systemctl() {
  local fakebin="$1" mode="$2"
  cat >"$fakebin/systemctl" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "--user" && "\$2" == "list-units" ]]; then
  exit 0
fi
if [[ "\$1" == "--user" && "\$2" == "show" ]]; then
  unit="\$3"
  prop="\${4#--property=}"
  case "$mode:\$unit:\$prop" in
    healthy:hermes-backup.timer:UnitFileState) echo "enabled" ;;
    healthy:hermes-backup.timer:ActiveState) echo "active" ;;
    healthy:hermes-backup.timer:NextElapseUSecRealtime) echo "Tue 2099-01-01 03:15:00 UTC" ;;
    healthy:hermes-backup.service:Result) echo "success" ;;
    disabled:hermes-backup.timer:UnitFileState) echo "disabled" ;;
    disabled:hermes-backup.timer:ActiveState) echo "inactive" ;;
    failing:hermes-backup.timer:UnitFileState) echo "enabled" ;;
    failing:hermes-backup.timer:ActiveState) echo "active" ;;
    failing:hermes-backup.timer:NextElapseUSecRealtime) echo "Tue 2099-01-01 03:15:00 UTC" ;;
    failing:hermes-backup.service:Result) echo "exit-code" ;;
    stale:hermes-backup.timer:UnitFileState) echo "enabled" ;;
    stale:hermes-backup.timer:ActiveState) echo "active" ;;
    stale:hermes-backup.timer:NextElapseUSecRealtime) echo "Tue 2020-01-01 03:15:00 UTC" ;;
    stale:hermes-backup.service:Result) echo "success" ;;
    *:automation-watchdog.timer:UnitFileState) echo "enabled" ;;
    *:automation-watchdog.timer:ActiveState) echo "active" ;;
    *:automation-watchdog.timer:NextElapseUSecRealtime) echo "Tue 2099-01-01 00:00:00 UTC" ;;
    *:automation-watchdog.service:Result) echo "success" ;;
    *) echo "" ;;
  esac
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl"
}

test_systemd_timer_disabled_reports_enable_fix() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "disabled"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "systemd"
  assert_contains "$output" "vanished"
  assert_contains "$output" "systemctl --user enable --now hermes-backup.timer"
}

test_systemd_service_failing_reports_result() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "failing"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "failing"
  assert_contains "$output" "exit-code"
  assert_contains "$output" "journalctl --user -u hermes-backup.service -n 50"
}

test_systemd_timer_stale_next_elapse_reports_stale() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "stale"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "stale"
  assert_contains "$output" "systemctl --user list-timers hermes-backup.timer"
}

test_systemd_healthy_reports_nothing() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "healthy"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_not_contains "$output" "systemd"
}
```

And add the 4 new calls right before the final `printf 'PASS...'` line:

```bash
test_systemd_timer_disabled_reports_enable_fix
test_systemd_service_failing_reports_result
test_systemd_timer_stale_next_elapse_reports_stale
test_systemd_healthy_reports_nothing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/automation-watchdog.test.sh`
Expected: FAIL — `ASSERT FAILED: expected output to contain: systemd` (function doesn't exist / isn't called yet, so no systemd-backend output appears).

- [ ] **Step 3: Write minimal implementation**

In `automation-watchdog/automation-watchdog`, add (after the `check_hermes_cron` function, before `main`):

```bash
TRACKED_TIMERS=(hermes-backup automation-watchdog)

check_systemd_timers() {
  if ! systemctl --user list-units --no-legend >/dev/null 2>&1; then
    return 1
  fi

  local name unit_file_state active_state result next_elapse next_epoch now_epoch
  now_epoch="$(date -u +%s)"

  for name in "${TRACKED_TIMERS[@]}"; do
    unit_file_state="$(systemctl --user show "${name}.timer" --property=UnitFileState --value 2>/dev/null || true)"
    active_state="$(systemctl --user show "${name}.timer" --property=ActiveState --value 2>/dev/null || true)"

    if [[ "$unit_file_state" != "enabled" || "$active_state" != "active" ]]; then
      printf 'systemd\tvanished\t%s\tsystemctl --user enable --now %s.timer\n' "$name" "$name"
      continue
    fi

    result="$(systemctl --user show "${name}.service" --property=Result --value 2>/dev/null || true)"
    if [[ -n "$result" && "$result" != "success" ]]; then
      printf 'systemd\tfailing\t%s\t%s.service last result=%s. Debug: journalctl --user -u %s.service -n 50\n' \
        "$name" "$name" "$result" "$name"
      continue
    fi

    next_elapse="$(systemctl --user show "${name}.timer" --property=NextElapseUSecRealtime --value 2>/dev/null || true)"
    if [[ -n "$next_elapse" && "$next_elapse" != "n/a" ]]; then
      next_epoch="$(date -d "$next_elapse" +%s 2>/dev/null || true)"
      if [[ -n "$next_epoch" && "$next_epoch" -lt "$now_epoch" ]]; then
        printf 'systemd\tstale\t%s\t%s.timer next fire is in the past (%s). Check: systemctl --user list-timers %s.timer\n' \
          "$name" "$name" "$next_elapse" "$name"
      fi
    fi
  done
}
```

Change `main()` to also call it:

```bash
main() {
  mkdir -p "$DATA_DIR"
  check_hermes_cron
  check_systemd_timers
}

main "$@"
```

Note: `NextElapseUSecRealtime`-in-the-past is a low-probability backstop (a healthy active+enabled timer's next-elapse is essentially always in the future by systemd's own bookkeeping) — the `UnitFileState`/`ActiveState`/`Result` checks are the primary detectors.

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/automation-watchdog.test.sh`
Expected: `PASS: automation-watchdog contract tests`

- [ ] **Step 5: Commit**

```bash
git add automation-watchdog/automation-watchdog tests/automation-watchdog.test.sh
git commit -m "feat(automation-watchdog): systemd timer backend detection"
```

---

### Task 3: Notification delivery, dry-run, exit codes

**Files:**
- Modify: `automation-watchdog/automation-watchdog` (replace `main`, add notify/log/sound functions)
- Modify: `tests/automation-watchdog.test.sh` (add 3 test functions)

**Interfaces:**
- Consumes: `alarm/alarm-trigger`'s `prepare_desktop_env()` body (copied verbatim, renamed variables not needed — function name and body reused as-is).
- Produces: final `main()` behavior — silent exit 0 when no problems; `--dry-run` prints tab-separated problem lines to stdout without calling `notify-send` or writing the snapshot; normal mode calls `notify-send -u critical` once per problem + plays a sound once per run (not once per problem) + appends every problem to `$LOG_FILE`; exit 1 only when **both** backends are unreadable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/automation-watchdog.test.sh` (again, before the final `printf 'PASS...'` line), plus their calls:

```bash
test_dry_run_does_not_call_real_notify_send() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  cat >"$fakebin/notify-send" <<'EOF'
#!/usr/bin/env bash
echo "notify-send called: $*" >>"$NOTIFY_LOG"
exit 0
EOF
  chmod +x "$fakebin/notify-send"
  export NOTIFY_LOG="$tmp/notify.log"
  : >"$NOTIFY_LOG"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {"job-1": {"name": "vanished-job", "schedule_display": "0 3 * * *", "script": "x.sh", "no_agent": true}}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "healthy"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "vanished-job"
  [[ ! -s "$NOTIFY_LOG" ]]
}

test_healthy_run_is_silent_and_exits_zero() {
  local tmp home data_dir fakebin rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  cat >"$fakebin/notify-send" <<'EOF'
#!/usr/bin/env bash
echo "notify-send called: $*" >>"$NOTIFY_LOG"
exit 0
EOF
  chmod +x "$fakebin/notify-send"
  export NOTIFY_LOG="$tmp/notify.log"
  : >"$NOTIFY_LOG"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "healthy"

  set +e
  HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" >/dev/null
  rc=$?
  set -e

  [[ "$rc" -eq 0 ]]
  [[ ! -s "$NOTIFY_LOG" ]]
}

test_both_backends_unreadable_exits_one() {
  local tmp home data_dir fakebin rc
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home/.hermes/cron" "$fakebin"
  printf 'not valid json' >"$home/.hermes/cron/jobs.json"

  cat >"$fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "Failed to connect to bus" >&2
exit 1
EOF
  chmod +x "$fakebin/systemctl"

  set +e
  HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" >/dev/null 2>&1
  rc=$?
  set -e

  [[ "$rc" -eq 1 ]]
}
```

And add the 3 new calls right before the final `printf 'PASS...'` line:

```bash
test_dry_run_does_not_call_real_notify_send
test_healthy_run_is_silent_and_exits_zero
test_both_backends_unreadable_exits_one
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/automation-watchdog.test.sh`
Expected: FAIL — `test_both_backends_unreadable_exits_one` fails first (`rc` is not 1; current `main` has no exit-code handling and `set -euo pipefail` would currently abort the whole script on the corrupt-JSON case instead of cleanly returning 1).

- [ ] **Step 3: Write minimal implementation**

Replace `main()` in `automation-watchdog/automation-watchdog` and add the notify/log/sound functions above it:

```bash
prepare_desktop_env() {
  local uid runtime_dir
  uid="$(id -u)"
  runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$uid}"

  export XDG_RUNTIME_DIR="$runtime_dir"

  if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "$runtime_dir/bus" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus"
  fi
}

try_play_sound() {
  local sound_file="/usr/share/sounds/freedesktop/stereo/dialog-warning.oga"

  if command -v paplay >/dev/null 2>&1 && [[ -f "$sound_file" ]]; then
    if paplay "$sound_file" >/dev/null 2>&1; then
      return 0
    fi
  fi

  if command -v pw-play >/dev/null 2>&1 && [[ -f "$sound_file" ]]; then
    if pw-play "$sound_file" >/dev/null 2>&1; then
      return 0
    fi
  fi

  if command -v canberra-gtk-play >/dev/null 2>&1; then
    if canberra-gtk-play -i dialog-warning -d automation-watchdog >/dev/null 2>&1; then
      return 0
    fi
  fi

  return 1
}

log_msg() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >>"$LOG_FILE"
}

notify_problem() {
  local backend="$1" kind="$2" name="$3" fix="$4"
  local title="Automation watchdog: $backend $kind"

  if command -v notify-send >/dev/null 2>&1; then
    if ! notify-send -u critical "$title" "$name: $fix"; then
      log_msg "notify-send failed for $backend/$name"
    fi
  else
    log_msg "notify-send not available for $backend/$name: $fix"
  fi

  log_msg "$backend $kind $name: $fix"
}

main() {
  mkdir -p "$DATA_DIR"
  touch "$LOG_FILE"

  local hermes_ok=1 systemd_ok=1
  local hermes_problems="" systemd_problems="" all_problems=""

  if hermes_problems="$(check_hermes_cron)"; then
    :
  else
    hermes_ok=0
  fi

  if systemd_problems="$(check_systemd_timers)"; then
    :
  else
    systemd_ok=0
  fi

  if [[ "$hermes_ok" == "0" && "$systemd_ok" == "0" ]]; then
    log_msg "both backends unreadable"
    exit 1
  fi

  all_problems="$(printf '%s\n%s' "$hermes_problems" "$systemd_problems" | sed '/^$/d')"

  if [[ -z "$all_problems" ]]; then
    exit 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    printf '%s\n' "$all_problems"
    exit 0
  fi

  prepare_desktop_env
  local sound_played=0
  while IFS=$'\t' read -r backend kind name fix; do
    [[ -z "$backend" ]] && continue
    notify_problem "$backend" "$kind" "$name" "$fix"
    if [[ "$sound_played" == "0" ]]; then
      try_play_sound || log_msg "sound playback failed"
      sound_played=1
    fi
  done <<<"$all_problems"

  exit 0
}

main "$@"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/automation-watchdog.test.sh`
Expected: `PASS: automation-watchdog contract tests`

- [ ] **Step 5: Commit**

```bash
git add automation-watchdog/automation-watchdog tests/automation-watchdog.test.sh
git commit -m "feat(automation-watchdog): notification delivery, dry-run, exit codes"
```

---

### Task 4: Systemd unit files

**Files:**
- Create: `automation-watchdog/automation-watchdog.timer`
- Create: `automation-watchdog/automation-watchdog.service`

**Interfaces:**
- Consumes: `~/.local/bin/automation-watchdog` (installed in Task 5).
- Produces: `automation-watchdog.timer`/`.service` unit file pair, structurally mirroring `hermes-backup.timer`/`.service` (`Persistent=true`, `Type=oneshot`).

This task has no bash/python logic to unit-test — its correctness is verified by the manual smoke check in the Final Verification Gate (units load and the timer schedules correctly) and by Task 5's installer test asserting the files land on disk.

- [ ] **Step 1: Create the service unit**

Create `automation-watchdog/automation-watchdog.service`:

```ini
[Unit]
Description=Automation watchdog (Hermes-cron + systemd timer health check)
Documentation=https://github.com/alex-irvine/linux-setup
ConditionPathExists=%h/.local/bin/automation-watchdog

[Service]
Type=oneshot
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/automation-watchdog
TimeoutStartSec=120
Nice=10
```

- [ ] **Step 2: Create the timer unit**

Create `automation-watchdog/automation-watchdog.timer`:

```ini
[Unit]
Description=Automation watchdog check (every 4h; persistent; catches up after suspend/resume)

[Timer]
OnCalendar=*-*-* 0/4:00:00
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Validate unit syntax**

Run: `systemd-analyze verify automation-watchdog/automation-watchdog.service automation-watchdog/automation-watchdog.timer`
Expected: exit code 0, no output. (`systemd-analyze verify` accepts arbitrary file paths and checks unit-file syntax without requiring the units to be installed first.)

- [ ] **Step 4: Commit**

```bash
git add automation-watchdog/automation-watchdog.timer automation-watchdog/automation-watchdog.service
git commit -m "feat(automation-watchdog): systemd unit files"
```

---

### Task 5: Installer script

**Files:**
- Create: `automation-watchdog/install-automation-watchdog.sh`
- Test: `tests/install-automation-watchdog.test.sh`

**Interfaces:**
- Consumes: `automation-watchdog/automation-watchdog`, `automation-watchdog/automation-watchdog.timer`, `automation-watchdog/automation-watchdog.service` (all three already exist from Tasks 1-4).
- Produces: idempotent installer, mirroring `alarm/install-alarm.sh`'s structure — `install_files()` + `enable_timer()` + `main()`, env-var overridable (`WATCHDOG_BIN_DIR`, `WATCHDOG_DATA_DIR`, `WATCHDOG_UNIT_DIR`, `WATCHDOG_SKIP_SYSTEMD`).

- [ ] **Step 1: Write the failing test**

Create `tests/install-automation-watchdog.test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT_DIR/automation-watchdog/install-automation-watchdog.sh"

test_install_places_files_and_data() {
  local tmp home_dir bin_dir data_dir unit_dir
  tmp="$(mktemp -d)"
  home_dir="$tmp/home"
  bin_dir="$home_dir/.local/bin"
  data_dir="$home_dir/.local/share/automation-watchdog"
  unit_dir="$home_dir/.config/systemd/user"
  mkdir -p "$home_dir"

  HOME="$home_dir" \
  WATCHDOG_BIN_DIR="$bin_dir" \
  WATCHDOG_DATA_DIR="$data_dir" \
  WATCHDOG_UNIT_DIR="$unit_dir" \
  WATCHDOG_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  [[ -x "$bin_dir/automation-watchdog" ]]
  [[ -f "$unit_dir/automation-watchdog.timer" ]]
  [[ -f "$unit_dir/automation-watchdog.service" ]]
  [[ -f "$data_dir/watchdog.log" ]]

  rm -rf "$tmp"
}

test_install_is_idempotent_on_rerun() {
  local tmp home_dir bin_dir data_dir unit_dir
  tmp="$(mktemp -d)"
  home_dir="$tmp/home"
  bin_dir="$home_dir/.local/bin"
  data_dir="$home_dir/.local/share/automation-watchdog"
  unit_dir="$home_dir/.config/systemd/user"
  mkdir -p "$home_dir"

  HOME="$home_dir" \
  WATCHDOG_BIN_DIR="$bin_dir" \
  WATCHDOG_DATA_DIR="$data_dir" \
  WATCHDOG_UNIT_DIR="$unit_dir" \
  WATCHDOG_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  echo "existing watchdog.log content" >>"$data_dir/watchdog.log"

  HOME="$home_dir" \
  WATCHDOG_BIN_DIR="$bin_dir" \
  WATCHDOG_DATA_DIR="$data_dir" \
  WATCHDOG_UNIT_DIR="$unit_dir" \
  WATCHDOG_SKIP_SYSTEMD=1 \
  bash "$INSTALLER" >/dev/null

  [[ -x "$bin_dir/automation-watchdog" ]]
  [[ -f "$unit_dir/automation-watchdog.timer" ]]
  [[ -f "$unit_dir/automation-watchdog.service" ]]
  grep -q "existing watchdog.log content" "$data_dir/watchdog.log"

  rm -rf "$tmp"
}

test_install_places_files_and_data
test_install_is_idempotent_on_rerun
printf 'PASS: install-automation-watchdog contract tests\n'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/install-automation-watchdog.test.sh`
Expected: FAIL — `bash: .../automation-watchdog/install-automation-watchdog.sh: No such file or directory`.

- [ ] **Step 3: Write minimal implementation**

Create `automation-watchdog/install-automation-watchdog.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${WATCHDOG_BIN_DIR:-$HOME/.local/bin}"
DATA_DIR="${WATCHDOG_DATA_DIR:-$HOME/.local/share/automation-watchdog}"
UNIT_DIR="${WATCHDOG_UNIT_DIR:-$HOME/.config/systemd/user}"

install_files() {
  mkdir -p "$BIN_DIR"
  mkdir -p "$DATA_DIR"
  mkdir -p "$UNIT_DIR"

  install -m 755 "$SCRIPT_DIR/automation-watchdog" "$BIN_DIR/automation-watchdog"
  install -m 644 "$SCRIPT_DIR/automation-watchdog.timer" "$UNIT_DIR/automation-watchdog.timer"
  install -m 644 "$SCRIPT_DIR/automation-watchdog.service" "$UNIT_DIR/automation-watchdog.service"

  touch "$DATA_DIR/watchdog.log"
}

enable_timer() {
  if [[ "${WATCHDOG_SKIP_SYSTEMD:-0}" == "1" ]]; then
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable --now automation-watchdog.timer
  fi
}

main() {
  install_files
  enable_timer

  printf '[automation-watchdog] installed to %s/automation-watchdog\n' "$BIN_DIR"
}

main "$@"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/install-automation-watchdog.test.sh`
Expected: `PASS: install-automation-watchdog contract tests`

- [ ] **Step 5: Commit**

```bash
git add automation-watchdog/install-automation-watchdog.sh tests/install-automation-watchdog.test.sh
git commit -m "feat(automation-watchdog): installer script"
```

---

### Task 6: Wire into endeavouros-setup.sh

**Files:**
- Modify: `endeavouros-setup.sh:611-617` (insert new block after the "Hermes backup timer" block)
- Test: `tests/endeavouros-automation-watchdog-wireup.test.sh`

**Interfaces:**
- Consumes: `$SCRIPT_DIR` (already defined at `endeavouros-setup.sh:4`), `automation-watchdog/install-automation-watchdog.sh` (Task 5).
- Produces: a new banner block calling the installer, positioned immediately after the existing "Hermes backup timer" block (same file, same conventions: `echo "==== ... ===="` banner, comment block explaining why).

- [ ] **Step 1: Write the failing test**

Create `tests/endeavouros-automation-watchdog-wireup.test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *"automation-watchdog/install-automation-watchdog.sh"* ]] || {
  echo "FAIL: automation-watchdog installer call missing"
  exit 1
}

[[ "$CONTENT" == *"list-timers automation-watchdog.timer"* ]] || {
  echo "FAIL: automation-watchdog timer diagnostic call missing"
  exit 1
}

echo "PASS: automation-watchdog wireup present"
```

> **Corrected during execution:** the first draft of this test asserted
> `enable --now automation-watchdog.timer` appears in `endeavouros-setup.sh`
> directly. It doesn't — that call lives inside
> `install-automation-watchdog.sh`'s `enable_timer()` (Task 5), which
> `endeavouros-setup.sh` just invokes. Running the test for real (per TDD)
> caught this; the assertion above checks the diagnostic `list-timers` call
> instead, which genuinely is in `endeavouros-setup.sh`.

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/endeavouros-automation-watchdog-wireup.test.sh`
Expected: FAIL — `FAIL: automation-watchdog installer call missing`

- [ ] **Step 3: Insert the wireup block**

In `endeavouros-setup.sh`, find this exact text (currently lines 616-618):

```
systemctl --user list-timers hermes-backup.timer --all || true

###########################################################
# Open Design daemon (systemd user service)
```

Replace it with:

```
systemctl --user list-timers hermes-backup.timer --all || true

###########################################################
# Automation watchdog (systemd user timer)
#
# Checks Hermes-cron jobs (~/.hermes/cron/jobs.json) and this repo's systemd
# --user timers (currently hermes-backup.timer and itself) every 4h for
# vanished/failing/stale state, notifying locally via notify-send with a fix
# command already in the body. Exists because hermes-backup-gdrive's
# Hermes-cron job disappeared silently on 2026-07-21 with no signal in
# either direction — see
# docs/superpowers/specs/2026-07-27-automation-watchdog-design.md.
###########################################################
echo "==== Automation watchdog ===="
bash "$SCRIPT_DIR/automation-watchdog/install-automation-watchdog.sh"
systemctl --user list-timers automation-watchdog.timer --all || true

###########################################################
# Open Design daemon (systemd user service)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/endeavouros-automation-watchdog-wireup.test.sh`
Expected: `PASS: automation-watchdog wireup present`

Also run: `bash -n endeavouros-setup.sh`
Expected: no output, exit code 0 (syntax still valid after the edit).

- [ ] **Step 5: Commit**

```bash
git add endeavouros-setup.sh tests/endeavouros-automation-watchdog-wireup.test.sh
git commit -m "feat(endeavouros-setup): wire up automation-watchdog"
```

---

### Task 7: README documentation

**Files:**
- Modify: `README.md` (append new section)
- Test: `tests/docs-automation-watchdog.test.sh`

**Interfaces:**
- Consumes: nothing (pure documentation).
- Produces: `## Automation watchdog` section, appended after the existing `## Alarm CLI` section (currently the last section in the file).

- [ ] **Step 1: Write the failing test**

Create `tests/docs-automation-watchdog.test.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README_FILE="$ROOT_DIR/README.md"
CONTENT="$(cat "$README_FILE")"

[[ "$CONTENT" == *"## Automation watchdog"* ]] || {
  echo "FAIL: README missing Automation watchdog section"
  exit 1
}

[[ "$CONTENT" == *"automation-watchdog --dry-run"* ]] || {
  echo "FAIL: README missing automation-watchdog --dry-run example"
  exit 1
}

[[ "$CONTENT" == *"~/.local/share/automation-watchdog/watchdog.log"* ]] || {
  echo "FAIL: README missing watchdog.log path"
  exit 1
}

echo "PASS: automation-watchdog docs contract checks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tests/docs-automation-watchdog.test.sh`
Expected: FAIL — `FAIL: README missing Automation watchdog section`

- [ ] **Step 3: Append the README section**

Append to the end of `README.md` (currently ends at line 183, after the `## Alarm CLI` section's last line `- data stored in \`~/.local/share/alarm-cli/alarms.tsv\`.`):

```markdown

## Automation watchdog

A systemd user timer (`automation-watchdog.timer`) checks Hermes-cron jobs
and this repo's systemd `--user` timers every 4 hours for jobs that have
vanished, are failing, or have gone stale — and sends a desktop notification
with the fix command already in the body. Silent when everything is
healthy.

Exists because the `hermes-backup-gdrive` Hermes-cron job was silently
removed on 2026-07-21 (migrated to `hermes-backup.timer` — see "Hermes
backup" above) and nothing signaled either way for days.

Installed by `endeavouros-setup.sh` via
`automation-watchdog/install-automation-watchdog.sh`, same pattern as the
Alarm CLI.

Design: [docs/superpowers/specs/2026-07-27-automation-watchdog-design.md](docs/superpowers/specs/2026-07-27-automation-watchdog-design.md)

Manual run:

```sh
automation-watchdog --dry-run   # preview without notifying
automation-watchdog             # normal run (silent if healthy)
```

Logs: `~/.local/share/automation-watchdog/watchdog.log`
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tests/docs-automation-watchdog.test.sh`
Expected: `PASS: automation-watchdog docs contract checks`

- [ ] **Step 5: Commit**

```bash
git add README.md tests/docs-automation-watchdog.test.sh
git commit -m "docs: document automation watchdog"
```

---

## Final Verification Gate

- [ ] Run the full new test set:

```bash
bash tests/automation-watchdog.test.sh && \
bash tests/install-automation-watchdog.test.sh && \
bash tests/endeavouros-automation-watchdog-wireup.test.sh && \
bash tests/docs-automation-watchdog.test.sh
```

Expected: all four `PASS:` lines, exit code 0.

- [ ] Run the full existing repo test set to confirm nothing else broke:

```bash
for f in tests/*.test.sh; do bash "$f" || echo "FAILED: $f"; done
```

Expected: every file prints its own `PASS:` line; no `FAILED:` lines.

- [ ] Shell syntax check:

```bash
bash -n automation-watchdog/automation-watchdog \
        automation-watchdog/install-automation-watchdog.sh \
        endeavouros-setup.sh
```

Expected: no output, exit code 0.

- [ ] Manual smoke check (real machine, not sandboxed):

```bash
bash automation-watchdog/automation-watchdog --dry-run
```

Expected: prints nothing (current real state is healthy — `hermes-backup.timer` active/enabled/last-success, `automation-watchdog.timer` not yet installed so this is the pre-install manual run). Then actually install it and confirm the timer is live:

```bash
bash automation-watchdog/install-automation-watchdog.sh
systemctl --user list-timers automation-watchdog.timer --all
```

Expected: shows a future NEXT time. Then break something on purpose and confirm a real desktop notification appears with a correct, runnable fix command — e.g. temporarily:

```bash
systemctl --user disable hermes-backup.timer
bash automation-watchdog/automation-watchdog
# confirm a desktop notification appeared, then:
systemctl --user enable --now hermes-backup.timer
```
