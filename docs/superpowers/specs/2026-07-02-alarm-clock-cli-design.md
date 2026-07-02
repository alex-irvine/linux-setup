# Alarm Clock CLI Design

Date: 2026-07-02
Repo: `linux-setup`
Status: Approved in chat, pending written spec review

## 1. Objective

Add a very simple alarm clock CLI that survives fresh installs and supports:
- adding alarms,
- deleting alarms,
- viewing alarms,
- firing with desktop notification + sound.

Primary goals:
- minimal implementation complexity,
- works out of this repo (no separate alarm repo),
- installed automatically during fresh machine setup,
- user-level command at `~/.local/bin/alarm`.

## 2. Decision Summary

### Chosen direction

Use a shell-based implementation inside this repo with `at` as scheduler backend:
- `alarm/` folder in `linux-setup` contains scripts.
- installer copies scripts into `~/.local/bin`.
- alarms persisted in a user data file under `~/.local/share/alarm-cli`.
- alarm execution uses `at` + an `alarm-trigger` helper script.

### Why this direction

Compared options:

1) Bash + `at` + metadata file (chosen)
- Pros: low complexity, aligns with existing repo style, no new runtime stack.
- Cons: recurring schedules deferred.

2) Python + sqlite + custom daemon
- Pros: richer model for future expansion.
- Cons: higher setup and maintenance overhead for current scope.

3) Generated systemd timer units per alarm
- Pros: native scheduler path.
- Cons: per-alarm unit sprawl and more complex list/delete behavior.

## 3. Scope

### In scope

- One-shot alarms only.
- Two input modes:
  - absolute local datetime,
  - relative duration (`--in`).
- CLI commands:
  - `alarm add ...`,
  - `alarm list`,
  - `alarm delete <alarm-id>`.
- Fire action in desktop session: sound + `notify-send` notification.
- Bootstrap integration in `endeavouros-setup.sh`.

### Out of scope

- Recurring/daily alarms.
- Headless/TTY-only notification guarantees.
- Separate standalone repository for alarm tooling.

## 4. Architecture

### 4.1 Components

1. `alarm/alarm` (main CLI)
- Handles command parsing and validation.
- Schedules alarms with `at`.
- Manages metadata store.

2. `alarm/alarm-trigger` (fire-time action)
- Plays notification sound.
- Emits desktop notification.
- Appends failure details to local log when needed.

3. `alarm/install-alarm.sh` (installer)
- Installs scripts to `~/.local/bin`.
- Creates data directory.
- Ensures required packages/services are present.

4. Metadata store
- `~/.local/share/alarm-cli/alarms.tsv`.
- Rows map CLI alarm ID to scheduler job ID and display metadata.

5. Log file
- `~/.local/share/alarm-cli/alarm.log`.

### 4.2 Data flow

Add flow:
1. User runs `alarm add <time> [label]` or `alarm add --in <duration> [label]`.
2. CLI normalizes target fire time.
3. CLI schedules `alarm-trigger` via `at`.
4. CLI parses scheduled `at` job id.
5. CLI appends metadata row.

List flow:
1. User runs `alarm list`.
2. CLI reads metadata rows.
3. CLI checks if each `at` job still exists.
4. CLI prints rows with stale indicator where job missing.

Delete flow:
1. User runs `alarm delete <alarm-id>`.
2. CLI resolves alarm-id to `at` job id.
3. CLI runs `atrm`.
4. CLI removes metadata row even if job already gone, with warning.

Fire flow:
1. `atd` executes `alarm-trigger` at scheduled time.
2. Trigger script attempts sound playback.
3. Trigger script sends `notify-send` notification.
4. If either action fails, script writes log context.

## 5. Command UX Contract

### 5.1 Add

Examples:
- `alarm add "2026-07-03 07:30" "Gym"`
- `alarm add --in 45m "Tea"`

Rules:
- label optional; defaults to `Alarm`.
- invalid datetime/duration returns exit code `2` with examples.
- scheduler failure returns exit code `1` and does not write metadata row.

### 5.2 List

- Displays: alarm-id, human-readable time, label, at-job-id, status.
- Status is `scheduled` or `stale`.
- v1 does not auto-prune stale rows.

### 5.3 Delete

- Accepts numeric alarm-id.
- Unknown alarm-id returns exit code `2` with hint to run `alarm list`.
- If `atrm` reports missing job, metadata still removed and warning printed.

### 5.4 Exit codes

- `0`: success
- `1`: operational/scheduler/runtime error
- `2`: user input/usage error

## 6. Dependency and Install Strategy

### 6.1 Runtime dependencies

- `at` (scheduler)
- `atd` service
- `notify-send` (`libnotify` package)
- sound player candidates in fallback chain:
  - `paplay` (preferred),
  - `pw-play`,
  - `canberra-gtk-play`.

### 6.2 Repo layout and bootstrap integration

- Add `alarm/` directory to this repo.
- `endeavouros-setup.sh` runs `bash "$SCRIPT_DIR/alarm/install-alarm.sh"`.
- Installer ensures idempotent reruns.
- Installer targets user-level binary path `~/.local/bin`.

## 7. Error Handling Strategy

- Parse/validation errors produce concise actionable message + examples.
- `at` scheduling failure: emit stderr and stop before metadata update.
- Stale metadata discovered in list: clearly marked, not auto-deleted in v1.
- Fire-time action:
  - try sound players in order,
  - still attempt notification if sound fails,
  - log any failures for debugging.

## 8. Verification Strategy

### 8.1 Automated contract tests (bash)

- add absolute alarm success path.
- add relative alarm success path.
- list includes scheduled entries.
- delete removes target entry.
- invalid time format returns `2`.
- scheduler failure preserves metadata integrity.

### 8.2 Idempotency checks

- run installer twice; no duplicate or broken state.
- verify `alarm` exists in `~/.local/bin` after rerun.

### 8.3 Manual smoke check

- run `alarm add --in 1m "test"`.
- verify sound plays and desktop notification appears.

## 9. Security and Operational Notes

- User-level install avoids system-wide binary mutation.
- No secret material required.
- Desktop-only notification behavior is explicit; no promise for headless sessions.

## 10. Implementation Readiness

Design is ready for implementation planning.

Planned execution order:
1. add alarm scripts + installer,
2. integrate installer in `endeavouros-setup.sh`,
3. add README section for command usage,
4. add/update bash tests for alarm contract.
