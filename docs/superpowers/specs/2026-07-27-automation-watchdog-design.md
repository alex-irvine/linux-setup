# Automation Watchdog Design

Date: 2026-07-27
Repo: `linux-setup`
Status: Approved in chat, pending written spec review

## 1. Objective

Send a single desktop notification — with the fix command already in the
body — when a scheduled background job (a Hermes `hermes-cron` job, or a
`systemd --user` timer this repo manages) vanishes, fails, or goes stale.

This exists because the `hermes-backup-gdrive` Hermes-cron job was
deliberately removed on 2026-07-21 (commit `ec60912`, migrated to
`hermes-backup.timer`) and nobody noticed anything either way for days —
there was no signal in either direction. The watchdog's job is to always
produce that signal, for this job and any other scheduled job added later,
without depending on the very things (Hermes gateway, a specific scheduler)
that could be the thing that's down.

## 2. Decision Summary

### Chosen direction

- Trigger: a dedicated `automation-watchdog.timer` (systemd `--user`),
  running every 4 hours, independent of the Hermes gateway.
- Implementation: bash driver script + inline `python3 -c` for JSON/API
  parsing, matching `alarm/alarm-trigger` and `hermes-backup-gdrive.sh` house
  style.
- Watches two backends every run: Hermes-cron (`~/.hermes/cron/jobs.json`)
  and systemd `--user` timers this repo manages.
- Notification via `notify-send` (+ optional sound), reusing
  `alarm/alarm-trigger`'s `prepare_desktop_env()` verbatim for
  `XDG_RUNTIME_DIR`/`DBUS_SESSION_BUS_ADDRESS` discovery instead of
  reinventing it.
- Read-only / observer only: never mutates a cron job or systemd unit.
  Notifies with the fix command; the human runs it.

### Why this direction

Compared options:

1) Dedicated systemd `--user` timer + dual-backend bash script (chosen)
   - Pros: independent of Hermes/gateway being alive (the actual failure mode
     that went unnoticed); reuses existing, tested `notify-send` session
     handling; matches this repo's established bash-script + systemd-timer
     style (`hermes-backup.timer`).
   - Cons: yet another systemd unit pair to maintain.

2) `hermes cron create --no-agent` watchdog job (inside Hermes)
   - Pros: one command to set up, visible via `hermes cron list`.
   - Cons: shares fate with the exact thing that broke — if the Hermes
     gateway/scheduler itself stops, this watchdog stops with it and reports
     nothing. Rejected for the same reason the backup itself was moved off
     hermes-cron.

3) Plain user crontab entry instead of a systemd timer
   - Pros: no unit files.
   - Cons: no `Persistent=true` catch-up after suspend, no `journalctl`
     history, inconsistent with how this repo already manages `hermes-backup`.
     Systemd timer is strictly better here and costs the same two files.

### Deliberate deviation from the `hermes-backup` precedent

`hermes-backup.timer`/`.service` are stowed from the separate `dotfiles`
repo's `systemd` package, and the backup script's canonical source lives in
`agent-lib` (copied into `~/.hermes/scripts` by its `install.sh`, because
Hermes only trusts real files — not symlinks — in that directory for
cron/no_agent scripts). This tool is **not** Hermes-specific (it also
watches plain systemd timers), so — per explicit direction — its script
*and* its unit files are versioned directly in `linux-setup`, the same repo
that owns `alarm/`. No `dotfiles` or `agent-lib` involvement.

## 3. Scope

### In scope

- Detect a hermes-cron job that:
  - existed in the previous snapshot and is now absent from
    `~/.hermes/cron/jobs.json` ("vanished"),
  - has `last_status == "error"` ("failing"),
  - has `next_run_at` older than now by more than one schedule period plus
    the job's own grace window ("stale").
- Detect a systemd `--user` timer, from a small hardcoded list of names the
  script tracks (not auto-discovery of every user timer — see §4.2), that:
  - is missing, disabled, or inactive ("vanished"/disabled),
  - has a linked service whose last `Result != success` ("failing"),
  - per `systemctl --user list-timers`, has a `NEXT` time already in the past
    ("stale" — should have fired and hasn't).
- One desktop notification per unhealthy item, each with a concrete,
  copy-pasteable fix command in the body.
- Silent (exit 0, no notification) when everything is healthy.
- `--dry-run` flag: print what would be notified, call nothing real.

### Out of scope

- Auto-healing (recreating a job, restarting a timer). Notify only.
- Any delivery channel other than the local desktop session
  (no email/SMS/Betterstack/Hermes-chat — considered and explicitly declined
  in brainstorming).
- Monitoring MCP OAuth health (clickup/composio/betterstack) — separate
  concern, out of scope for this pack.
- A historical dashboard or trend report. `~/.local/share/automation-watchdog/watchdog.log`
  is append-only diagnostic output, not a UI.
- Watching arbitrary third-party systemd timers (e.g. flatpak update timers)
  not owned by this repo.

## 4. Architecture

### 4.1 Components

1. `automation-watchdog/automation-watchdog` (main script)
   - Loads previous snapshot, runs both backend checks, aggregates problems,
     notifies if any, writes updated snapshot.
2. `automation-watchdog/automation-watchdog.timer` +
   `automation-watchdog.service` (systemd `--user` units)
   - `OnCalendar=*-*-* 00/4:00:00`, `Persistent=true` (same catch-up pattern
     as `hermes-backup.timer`).
3. `automation-watchdog/install-automation-watchdog.sh` (installer)
   - Copies the script to `~/.local/bin/automation-watchdog`.
   - Copies the two unit files to `~/.config/systemd/user/`.
   - Runs `systemctl --user daemon-reload` and
     `systemctl --user enable --now automation-watchdog.timer`.
   - Idempotent (safe to re-run, matches `alarm`'s installer pattern).
4. Snapshot + log store: `~/.local/share/automation-watchdog/`
   - `snapshot.json` — last-seen state per watched item (backend, id/name,
     enough of its config to reconstruct a fix command).
   - `watchdog.log` — append-only diagnostic log (notify-send/session
     failures, systemctl errors, etc.), same role as `alarm.log`.

### 4.2 Data flow

1. Load `snapshot.json` (empty structure on first run).
2. **Hermes-cron backend:** read `~/.hermes/cron/jobs.json`. For every job
   with `enabled` true and `state != "paused"`:
   - vanished: present in snapshot, absent now → fix text reconstructs
     `hermes cron create "<schedule>" --name <name> --script <script>
     [--no-agent]` from the snapshot's saved config.
   - failing: `last_status == "error"` → fix text includes `last_error` and
     `bash ~/.hermes/scripts/<script>` to reproduce.
   - stale: `next_run_at` older than now by > period + grace → fix text
     points at `hermes cron list` / `hermes gateway status`.
3. **Systemd backend:** enumerate the `.timer` units named in a hardcoded
   `TRACKED_TIMERS` list in the script — currently `hermes-backup.timer` and,
   for failure-detection only, `automation-watchdog.timer` itself (self-
   inclusion cannot catch its own vanished/disabled state — see §7 — but can
   catch its own previous run having failed). Extend the list by hand when a
   new timer is added. For each: `systemctl --user is-enabled`, `is-active`, and
   `show <service> --property=Result` plus `list-timers` NEXT column.
   - vanished/disabled: fix text is `systemctl --user enable --now <timer>`.
   - failing: fix text includes the `Result` value and
     `journalctl --user -u <service> -n 50`.
   - stale: fix text points at `systemctl --user list-timers`.
4. Diff current state against snapshot for both backends to catch
   "vanished" (see §3); update snapshot regardless of outcome (self-healing
   baseline — an intentional removal fires exactly one vanished alert next
   run, which is acceptable).
5. If the aggregated problem list is empty: exit 0, no notification, log
   nothing (matches the "classic watchdog pattern" already used by
   `no_agent` Hermes-cron jobs and by `hermes-backup-gdrive.sh` itself).
6. Otherwise: source `alarm-trigger`'s `prepare_desktop_env()`, call
   `notify-send` once per problem (title = backend + item name + kind, body
   = fix command), attempt the same sound fallback chain, and append each
   problem to `watchdog.log` regardless of notify-send's success.
7. Persist updated snapshot.

## 5. Command UX Contract

This is a background tool, not an interactive CLI — no subcommands.

```sh
automation-watchdog            # normal run: check, notify if unhealthy, exit 0
automation-watchdog --dry-run  # print what would be notified; no notify-send, no snapshot write
```

Exit codes:
- `0`: ran successfully, healthy or not (notification failure is logged, not
  a fatal exit — see §7).
- `1`: could not read either backend's state at all (e.g. both
  `~/.hermes/cron/jobs.json` unreadable and `systemctl --user` unreachable).

## 6. Dependency and Install Strategy

### 6.1 Runtime dependencies

- `notify-send` (`libnotify`) — already required by `alarm-cli`, already
  installed.
- `paplay` / `pw-play` / `canberra-gtk-play` (optional, sound fallback chain)
  — already required by `alarm-cli`.
- `python3` — already required by `hermes-backup-gdrive.sh`.
- `systemctl --user` (systemd) — already in use for `hermes-backup.timer`.

### 6.2 Repo layout and bootstrap integration

- Add `automation-watchdog/` directory to `linux-setup` (script, two unit
  files, installer) — mirrors the `alarm/` layout.
- `endeavouros-setup.sh` runs
  `bash "$SCRIPT_DIR/automation-watchdog/install-automation-watchdog.sh"`,
  placed next to the existing `hermes-backup.timer` enable step.
- README gets a new `## Automation watchdog` section mirroring the existing
  `## Hermes backup (Google Drive)` and `## Alarm CLI` sections.

## 7. Error Handling Strategy

- `notify-send` unavailable or no desktop session reachable: log to
  `watchdog.log`, continue (never treat this as fatal) — exact same
  degradation pattern as `alarm-trigger`'s `send_notification()`.
- One backend unreadable (malformed `jobs.json`, `systemctl --user`
  unreachable): log and skip that backend's checks for this run; still run
  the other backend. Only exit `1` if *both* fail.
- Self-watch caveat: `automation-watchdog.timer` cannot detect its own
  complete disappearance (if its own unit is removed, nothing fires to
  notice). This is accepted residual risk — closing it fully would need an
  external (non-local) dead-man's-switch, which was explicitly declined in
  brainstorming in favor of local desktop notifications. Documented here so
  it isn't rediscovered as a surprise later.

## 8. Verification Strategy

### 8.1 Automated contract tests (bash, `tests/automation-watchdog.test.sh`)

Following the existing `tests/alarm-trigger.test.sh` fakebin pattern (fake
`notify-send`, `systemctl`, `journalctl` on `PATH`):

- hermes-cron job present in snapshot, absent from a fixture `jobs.json` →
  notify-send called with a reconstructed `hermes cron create ...` command
  in the body.
- hermes-cron job with `last_status: "error"` → notify-send called,
  `last_error` present in body.
- systemd timer fixture reporting `Result=failed` → notify-send called.
- systemd timer fixture missing/disabled → notify-send called with
  `systemctl --user enable --now` in the body.
- everything healthy → notify-send **not** called, exit `0`.
- `--dry-run` → prints the would-be notification, notify-send **not**
  called.
- both backends unreadable → exit `1`.

### 8.2 Idempotency checks

- Run `install-automation-watchdog.sh` twice; confirm no duplicate units,
  `~/.local/bin/automation-watchdog` unchanged in behavior, timer still
  `enabled`/`active`.

### 8.3 Manual smoke check

- Temporarily rename `hermes-backup.timer` (or hand-edit the snapshot to
  drop a known-good hermes-cron job) and run `automation-watchdog` directly;
  confirm a real desktop notification appears with a correct, runnable fix
  command.

## 9. Security and Operational Notes

- Read-only with respect to both backends — never edits `jobs.json` or any
  systemd unit. Pure observer, matching the "no auto-heal" scope decision.
- Snapshot/log live under `~/.local/share/automation-watchdog/`, mirroring
  `~/.local/share/alarm-cli/` — user-level, no elevated permissions needed.
- No secrets read or stored (snapshot only holds schedule/script-path
  metadata, never `.env`/`auth.json` contents).

## 10. Implementation Readiness

Design is ready for implementation planning.

Planned execution order:
1. `automation-watchdog` script (both backend checks + snapshot diff +
   notify, `--dry-run` flag).
2. `automation-watchdog.timer`/`.service` unit files.
3. `install-automation-watchdog.sh` installer.
4. Wire installer into `endeavouros-setup.sh`.
5. README `## Automation watchdog` section.
6. `tests/automation-watchdog.test.sh` (contract tests from §8.1).
7. Final verification gate: full existing `tests/` suite + new test file,
   `bash -n` syntax check, manual smoke check from §8.3.
