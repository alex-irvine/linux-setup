# linux-setup

Fresh OS bootstrap. EndeavourOS/Arch host.

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
2. Clones `~/dotfiles` and stows every package (sway, foot, mako, nvim,
   tmux, tmuxinator, waybar, zsh, gtk, systemd, **claude**).
3. Installs apps + CLIs: yay, Go, Node, Neovim, Nerd Fonts, Rust,
   tree-sitter, Oh My Zsh, tmux + tpm, Chrome, Docker, kubectl, helm,
   k9s, flux, bottom, earlyoom, Evolution + ews, git/gh, lazygit, tig,
   Beekeeper, Remmina, LibreOffice, az cli, Copilot CLI, gonzo, logcli, yq, air.
4. Pulls private `lazyorc` + `lazyfleet` releases via gh.
5. Runs `claude-setup.sh` — installs Claude Code CLI, rtk, marketplaces
   (caveman, claude-plugins-official, claude-hud), plugins.
6. Runs `setup-vpn.sh` — imports the OpenVPN profile into NetworkManager
   (only if you've placed it locally — see VPN below).

Idempotent. Re-run safe.

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
