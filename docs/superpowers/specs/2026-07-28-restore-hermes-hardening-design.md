# Restore-Hermes Hardening + New-Laptop Runbook Design

Date: 2026-07-28
Repo: `linux-setup`
Status: Approved in chat, pending written spec review

## 1. Objective

Close the gaps found while auditing whether a Hermes backup is actually
sufficient to fully restore on a brand-new laptop: enshrine what can only
ever be tribal/manual knowledge in a runbook, automate what's genuinely
automatable, and turn a silent-skip into an active prompt where the answer
truly requires a human (first-time OAuth consent) but the *offer* to do it
doesn't.

None of this fixes a currently-broken thing — `restore-hermes.sh` today
behaves correctly for same-host restores and gracefully no-ops when
prerequisites are missing. This closes blind spots that would only bite on
an actual new-machine restore, which is precisely the scenario nobody has
exercised yet.

## 2. Decision Summary

### Chosen direction

Three targeted changes to `restore-hermes.sh` (the file this repo already
owns and tests), plus one new standalone runbook doc:

1. `offer_rclone_config()` — actively offer to run `rclone config` when a
   real terminal is available and not `--yes`; unchanged silent-skip
   fallback otherwise.
2. Cross-host backup selection — same interactive UX, now `/dev/tty`-robust
   (mirroring `install.sh:2282`'s exact technique) instead of plain `read`;
   `--yes`/no-tty now auto-picks the single most recent archive across all
   host folders instead of hanging.
3. Root-profile gateway reinstall — mirror hermes's own `.env`
   messaging-token check (`install.sh:2310`'s exact var list) and auto-run
   `hermes gateway install` when applicable, closing the blind spot where
   `hermes import` reminds named profiles but never the root one.
4. `NEW-LAPTOP.md` — the full runbook, including the one thing that
   genuinely cannot be automated (first browser OAuth for rclone) and its
   headless fallback (`rclone authorize`).

### Why this direction

Compared options:

1) Fix directly in `restore-hermes.sh` + new doc (chosen)
   - Pros: this repo already owns, tests, and version-controls this exact
     file; every fix reuses a pattern already proven correct elsewhere in
     this codebase (`/dev/tty` probe from `install.sh`, the
     `enable_backup_timer()` post-restore-action pattern already in this
     same file, the `TAILSCALE.md` standalone-doc convention).
   - Cons: none identified — this is squarely inside the repo's existing
     ownership boundary.

2) Patch `hermes-agent` core (`backup.py`'s post-import messaging) to also
   remind about the root profile
   - Pros: fixes it at the source, benefits every hermes-agent user, not
     just this machine.
   - Cons: separate upstream repo with its own contribution rubric
     (reproduce-on-main, PR review, footprint discipline); out of scope for
     "get this laptop's restore path solid" and not something this session
     should take on unilaterally. Worth reporting upstream separately, but
     not blocking on it — rejected for *this* work, noted as a possible
     follow-up.

3) Fully automate `rclone config` (skip the prompt, just run it)
   - Pros: zero extra interaction.
   - Cons: OAuth consent is a real human decision (which Google account,
     confirming scopes) — silently launching a browser flow without asking
     first would be a worse UX than the current silent skip, not better.
     Rejected — this is exactly the "needs a human, but doesn't need to be
     silent about needing one" case the prompt-where-appropriate bucket
     exists for.

## 3. Scope

### In scope

- `offer_rclone_config()`: tty-aware prompt-then-run for `rclone config`,
  falling back to today's print-and-exit-0 behavior whenever a real answer
  can't be obtained (no tty, `--yes`, or user declines).
- Cross-host archive selection: `/dev/tty`-robust interactive path (same
  UX as today) + new `--yes`/no-tty auto-select-most-recent-across-hosts
  path.
- Root-profile gateway reinstall: `.env` messaging-token check + auto
  `hermes gateway install`, mirroring hermes's own env-var list exactly.
- `NEW-LAPTOP.md`: full runbook — what's/isn't backed up, first-time
  `rclone config` (+ headless fallback), hostname-mismatch behavior (now
  automated, but worth documenting what it does), the root-gateway
  auto-install this change adds, and an explicit "by design, not a bug"
  note about `config.yaml`/`SOUL.md` being absent from the Hermes-native
  zip (they're symlinks on this host; dotfiles-stow + `agent-lib/install.sh`
  recreate them independently — see the "Intentional design, not a gap"
  pattern called out in `hermes-agent`'s own `AGENTS.md`).

### Out of scope

- Patching `hermes-agent` core (option 2 above) — noted as a possible
  future upstream report, not undertaken here.
- Backing up `~/.config/rclone/rclone.conf` itself. Considered and
  rejected: the fundamental bootstrap problem (need *some* credential to
  reach the backup that's supposed to restore everything) can't be solved
  by including the very credential that gates access to Drive inside a
  backup that lives *on* Drive. A local-disk-only companion backup of
  rclone.conf was considered too, but that only helps a same-disk restore,
  not a genuinely new laptop — no different from just re-running
  `rclone config`, so not worth the added complexity.
- Any change to `hermes-setup.sh`'s or `endeavouros-setup.sh`'s own
  invocation of `restore-hermes.sh` — the existing `"$RESTORE_SCRIPT" --yes`
  call site is unchanged; all new behavior triggers based on tty
  availability and the already-existing `--yes` flag.
- Testing the two genuinely-interactive branches (offering to run
  `rclone config`; the interactive host picker) with an automated test —
  see §8.

## 4. Architecture

### 4.1 Components (all within `restore-hermes.sh` unless noted)

1. `offer_rclone_config()` — new function, called in place of the current
   inline `if ! rclone listremotes ...` block's direct exit.
2. `resolve_cross_host_remote()` — replaces `prompt_for_remote_dir()`;
   returns `"<remote-dir> <archive-name>"` on stdout, or nothing (caller
   treats as "not found").
3. `maybe_install_root_gateway()` — new function, called after
   `hermes import ... --force` and `enable_backup_timer`.
4. `NEW-LAPTOP.md` — new standalone doc at repo root, linked from `README.md`
   the same way `TAILSCALE.md` already is.

### 4.2 Data flow

**`offer_rclone_config()`** (replaces the current early-exit block):
1. If `rclone listremotes` already lists `gdrive:` → no-op, continue script
   as today.
2. Else, probe `: </dev/tty` (same technique as `install.sh:2282`).
   - No tty, or `ASSUME_YES=1` → print today's exact instructions, `exit 0`.
   - Real tty and not `--yes` → prompt via `/dev/tty`: `"gdrive remote not
     configured. Run 'rclone config' now? [Y/n]"` (default yes). If the
     answer is no → same print-and-exit-0 fallback.
   - If yes → run `rclone config` with stdin/stdout attached to `/dev/tty`
     (`rclone config </dev/tty >/dev/tty 2>&1`), then re-check
     `rclone listremotes`. Configured now → continue the script normally.
     Still not configured (user backed out mid-wizard) → same
     print-and-exit-0 fallback.

**`resolve_cross_host_remote()`** (called only when the hostname-scoped
`DEFAULT_REMOTE` path had nothing, exactly like today's
`prompt_for_remote_dir()` call site):
1. `rclone lsf "$BASE_REMOTE/" -R --files-only | grep -E '^[^/]+/hermes-.*\.zip$' | sort -t/ -k2`
   — one recursive listing, all hosts' archives. **Must sort by field 2
   (`sort -t/ -k2`, i.e. the `hermes-YYYYMMDDTHHMMSSZ.zip` filename only),
   not a plain `sort`** — sorting the full `host/filename` string would
   order by hostname first and only then by timestamp, which would pick
   the wrong "most recent" whenever host names don't happen to sort the
   same way their backups' recency does. (Caught in spec self-review —
   `sort` alone was the first draft here and was wrong.)
2. Empty → return failure (existing "no backup archive found anywhere" path
   unchanged).
3. `ASSUME_YES=1` OR no tty (`: </dev/tty` probe) → take the last (most
   recent) line, split into host-dir/archive, `log` which one was
   auto-selected, return it. No prompt, no possibility of hanging.
4. Otherwise (interactive) → today's exact UX (numbered host-folder list,
   pick one, take that host's latest archive) with the prompt/read now
   going through `/dev/tty` instead of plain stdin.

**`maybe_install_root_gateway()`** (called once, unconditionally, right
after `enable_backup_timer` in the main flow):
1. If `~/.hermes/.env` doesn't exist → return (nothing restored, nothing
   to do).
2. For each of `TELEGRAM_BOT_TOKEN DISCORD_BOT_TOKEN SLACK_BOT_TOKEN
   SLACK_APP_TOKEN WHATSAPP_ENABLED` (exact list from `install.sh:2310`):
   if set and not the placeholder `your-token-here` → `log` which one
   triggered it, run `hermes gateway install`, return (only needs to fire
   once).
3. None set → return silently (nothing to install, matches
   `maybe_start_gateway()`'s own `HAS_MESSAGING=false` no-op in
   `install.sh:2318-2320`).

## 5. Command UX Contract

No new flags. `restore-hermes.sh`'s existing `--remote`, `--archive`,
`--yes`, `--dry-run`, `-h/--help` are unchanged; the new behavior is purely
tty-aware branching inside the existing flow. `--dry-run` still stops
before `hermes import` (unchanged), so it also skips the new
`maybe_install_root_gateway()` call (that only runs after a real import).

## 6. Dependency and Install Strategy

No new runtime dependencies — `rclone`, `hermes`, `systemctl` are already
required by this script today. No new repo layout; all changes are inside
the existing `restore-hermes.sh` plus one new top-level `.md` file, matching
how `TAILSCALE.md` sits alongside `README.md` today.

## 7. Error Handling Strategy

Every new branch's failure mode is "fall through to today's existing,
already-correct behavior" — never a new way to hang or hard-fail:
- `offer_rclone_config()`: any no/decline/still-unconfigured outcome ends in
  the same print-instructions-and-`exit 0` the script already does today.
- `resolve_cross_host_remote()`: empty listing still returns failure exactly
  like `prompt_for_remote_dir()` does today; the auto-select path cannot
  block since it never calls `read`.
- `maybe_install_root_gateway()`: `hermes gateway install` failing is
  logged (`"hermes gateway install failed; run it manually"`) and does not
  abort the script — the restore itself already succeeded by this point.

## 8. Verification Strategy

### 8.1 Automated contract tests (bash, extending `tests/restore-hermes.test.sh`)

Fully testable (no tty dependency, using the existing fakebin pattern):
- Cross-host auto-select: multiple host folders with archives at different
  timestamps, `--yes` passed → asserts the *newest across all hosts* (not
  just alphabetically-last host name) is selected and `hermes import`
  receives that exact archive.
- Root gateway auto-install: fixture `.env` with a messaging token set →
  fake `hermes` records a `gateway install` call after the `import` call.
- Root gateway skipped: fixture `.env` with no messaging tokens (or no
  `.env` at all) → fake `hermes` records no `gateway install` call.
- `gdrive` not configured, `--yes` passed (no tty in test harness anyway)
  → prints the existing instructions, exits 0, does not hang. (Not
  currently tested at all today — every existing fixture pre-configures
  `gdrive:`, so this is new coverage, not just a regression check.)

### 8.2 Manual verification (not automatable — see §3)

`: </dev/tty` availability can't be faked the way a `PATH` binary can (same
limitation `install.sh` itself lives with — it doesn't test its own
tty-dependent branches either). Verify these two by hand, from a real
terminal:
- Temporarily `rclone config disconnect gdrive:`-equivalent (or point
  `--remote` at a fresh unconfigured setup) and confirm the "run rclone
  config now?" prompt appears and, on accepting, actually launches the real
  `rclone config` wizard attached to the terminal.
- With backups present under a different (fake) hostname folder and no
  `--yes`, confirm the interactive host-picker prompt still works reading
  from a real terminal.

### 8.3 Idempotency

`maybe_install_root_gateway()` calling `hermes gateway install` on a host
where the gateway is already installed must not error the whole script —
confirmed via `hermes gateway install`'s own idempotency (already relied on
implicitly by the fact that `hermes-setup.sh` / `endeavouros-setup.sh` can
be re-run safely today); this change doesn't introduce a new idempotency
requirement beyond what `hermes gateway install` itself already guarantees.

## 9. Security and Operational Notes

- `offer_rclone_config()` never runs `rclone config` without an explicit
  yes from a real human at a real terminal — no silent OAuth flows.
- `maybe_install_root_gateway()` only reads `.env` to check for the
  *presence* of a handful of known var names; never logs or prints token
  values.
- No new secrets are read, stored, or transmitted anywhere this design
  didn't already touch.

## 10. Implementation Readiness

Design is ready for implementation planning.

Planned execution order:
1. `resolve_cross_host_remote()` (replaces `prompt_for_remote_dir()`) +
   cross-host auto-select test.
2. `maybe_install_root_gateway()` + gateway auto-install/skip tests.
3. `offer_rclone_config()` (replaces the inline not-configured check) +
   not-configured/`--yes` test.
4. `NEW-LAPTOP.md` + link from `README.md`.
5. Final verification gate: full existing + new `restore-hermes.test.sh`
   assertions, `bash -n` syntax check, the two manual checks from §8.2.
