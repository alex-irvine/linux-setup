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
