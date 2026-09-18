# linux-setup

Fresh OS bootstrap for an EndeavourOS/Arch host.

## Repository scope

This repository owns application installation and base operating-system configuration: pacman/yay packages, system services, `/etc` configuration, hardware/network setup, and bootstrap scripts.

It does not own user configuration, shell aliases, application dotfiles, shared skills, provider adapters, or user workflow scripts. Those belong in the GNU Stow repository at `~/dotfiles`. Application and project repositories belong under `~/Proj`; runtime state and secrets stay untracked in their owning runtime directories.

Browser automation is configured by `~/dotfiles`: parent agents delegate to dedicated browser-debugger children that load a pinned Chrome DevTools MCP. Linux setup does not install a browser agent runtime or register browser MCPs globally.

## Run

```sh
# Pre-reqs on a bare system: git + this repo.
sudo pacman -Sy --noconfirm git
git clone https://github.com/<you>/linux-setup.git ~/Proj/linux-setup
bash ~/Proj/linux-setup/endeavouros-setup.sh
```

Interactive: `gh auth login` (browser device code) runs early so the
private `dotfiles` clone can authenticate via the gh credential helper.
Sudo password cached for pacman/yay.

## What it does

1. pacman base tools + `github-cli` → `gh auth login` (gates dotfiles clone).
2. Clones `~/dotfiles` and stows every package (sway, ghostty, mako, nvim,
   tmux, tmuxinator, waybar, zsh, gtk, systemd, git, k9s, lazygit,
   **agents**, **claude**, **opencode**, **hermes**).
3. Installs apps + CLIs: yay, Go, Node, Neovim, Nerd Fonts, Rust,
   tree-sitter, Oh My Zsh, tmux + tpm, Chrome, Docker, kubectl, helm,
   k9s, flux, bottom, earlyoom, Evolution + ews, git/gh, lazygit, tig,
   Beekeeper, Remmina, LibreOffice, az cli, Copilot CLI, gonzo, logcli, yq, air.
4. Pulls private `lazyorc` + `lazyfleet` releases via gh.
5. Runs `claude-setup.sh` — installs Claude Code CLI, rtk, marketplaces
   (caveman, claude-plugins-official, claude-hud), plugins. Then installs
   **graphify** (pinned, `uv tool`) — the knowledge-graph backend the dotfiles
   `graph-scout` subagent queries over MCP. `graphify install` is deliberately
   not run; the stowed `graph-scout-mcp` launcher is the only entry point.
6. Runs `firecrawl-setup.sh` first (ensures `~/.hermes/.env` has
   `FIRECRAWL_API_KEY`/`FIRECRAWL_API_URL`). Hermes is the only consumer,
   reading them for its `web.backend: firecrawl` search path. The firecrawl
   CLI is deliberately not installed: agents reach Firecrawl through the
   Composio MCP behind an isolated provider child.
   Runs hermes-setup.sh (Hermes install, product-operations venv build,
   restore bootstrap).
7. Runs `agent-memory-setup.sh` to install the shared local memory CLI, stow the
   canonical vault, provision local Ollama models, and enable its worker timer.
8. Enables the persistent `hermes-backup.timer` (systemd user timer) for daily
   Google Drive backups; catches up after suspend/resume.
9. Runs `setup-vpn.sh` — imports the OpenVPN profile into NetworkManager
   (only if you've placed it locally — see VPN below).

## Hermes backup (Google Drive)

Backups run via a **systemd user timer** (`hermes-backup.timer`, stowed from the
dotfiles `systemd` package) that runs `~/.hermes/scripts/hermes-backup-gdrive.sh`
daily at 03:00. `Persistent=true` means a run missed while the laptop is
suspended/off fires shortly after the next resume — so a machine asleep at 3am
still gets backed up. Lingering is enabled so it runs without an active session.
(The backup script itself is copied, not symlinked, into `~/.hermes/scripts` by
`hermes-bots/install.sh` — Hermes sandboxes cron scripts to that directory.)

First-run activation:

```sh
rclone config
rclone lsd gdrive:
~/Proj/linux-setup/restore-hermes.sh
```

Restore policy during bootstrap:
- auto-restore latest backup from same-host path when present,
- prompt only when same-host path is empty and other host folders exist.

The timer is enabled after the restore step so a fresh empty snapshot cannot
overwrite prior remote state before you import a previous backup.

`restore-hermes.sh` restores the latest archive and enables the backup timer
automatically.

Idempotent. Re-run safe.

Full new-laptop restore runbook: [NEW-LAPTOP.md](NEW-LAPTOP.md)

## Shared agent memory

`agent-memory-setup.sh` installs the local `memoryctl` service used by Claude,
OpenCode, and Hermes. The canonical Markdown vault is stowed from
`~/dotfiles/agents/.agents/memory` to `~/.agents/memory`; SQLite search state is
rebuildable, Ollama supplies local embeddings and capture review, and a user
timer drains the durable capture queue. No hosted credential is required.

## Layout

- `endeavouros-setup.sh` — main entry point.
- `claude-setup.sh` — Claude Code CLI + plugins. Called by main; safe standalone.
- `apply-etc.sh` + `etc/` — `/etc` drop-ins (PAM, sysctl, NetworkManager prefer-wired route metrics, etc). Executable sources install 755, plain configs 644.
- `popos-setup.sh` — legacy Pop!_OS variant.
- `fix-suspend.sh` — laptop suspend tweaks.
- `setup-vpn.sh` — imports OpenVPN profile into NetworkManager. Called by main; safe standalone.

## VPN

Profile is **confidential** (inline private key, user-locked, 2FA) — never committed.

1. Fetch profile from **https://86.28.72.134/** — log in as your user, download the user-locked `.ovpn`.
2. Place it: `mkdir -p ~/.config/vpn && mv ~/Downloads/profile-userlocked.ovpn ~/.config/vpn/ && chmod 600 ~/.config/vpn/profile-userlocked.ovpn`
3. Import: `bash setup-vpn.sh`

Connect / disconnect (aliases in dotfiles `zsh`):

| Alias | Command |
|---|---|
| `vpn-up` | `nmcli --ask connection up profile-userlocked` (prompts password + 2FA code) |
| `vpn-down` | `nmcli connection down profile-userlocked` |

## Claude config persistence

All Claude config lives in `~/dotfiles/claude/`. Stowing creates:

| Link | Target |
|---|---|
| `~/.claude/settings.json` | `dotfiles/claude/.claude/settings.json` |
| `~/.claude/agents/` | `dotfiles/claude/.claude/agents/` |
| `~/.claude/commands/` | `dotfiles/claude/.claude/commands/` |
| `~/.claude/plugins/blocklist.json` | `dotfiles/claude/.claude/plugins/blocklist.json` |
| `~/.claude/projects/-home-alex-Proj/memory/` | `dotfiles/claude/.claude/projects/-home-alex-Proj/memory/` |

Plugins + marketplaces re-installed by `claude-setup.sh` from `settings.json`.
Credentials (`~/.claude/.credentials.json`) + session jsonl stay local — never tracked.

## Remote tmux via Tailscale

Use Tailscale + SSH to attach to running tmux sessions from mobile without exposing public terminal endpoints.

- Host setup and troubleshooting: [TAILSCALE.md](TAILSCALE.md)
- Mobile requirements are documented there (manual install).
- Manual smoke flow: [TAILSCALE.md](TAILSCALE.md#manual-smoke-test-command-flow)
- Verification log template: [TAILSCALE.md](TAILSCALE.md#verification-log-template)

## Alarm CLI

Installed by `endeavouros-setup.sh` to `~/.local/bin/alarm` via `alarm/install-alarm.sh`.

Commands:

```sh
alarm add "2026-07-03 07:30" "Gym"
alarm add --in 45m "Tea"
alarm list
alarm delete <alarm-id>
```

Runtime notes:
- one-shot alarms only,
- desktop session notifications (`notify-send`) + notification sound on fire,
- data stored in `~/.local/share/alarm-cli/alarms.tsv`.

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
