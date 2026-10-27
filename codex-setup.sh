#!/usr/bin/env bash
set -euo pipefail

###########################################################
# Codex CLI setup
#
# Installs the official Codex CLI from the Arch `extra` repo and signs it in.
#
# ~/.codex config, rules, hooks, subagents, and provider children come from
# the `codex` Stow package in ~/dotfiles; shared skills come from the `agents`
# package. Both are applied by endeavouros-setup.sh; run that first.
#
# Provider MCPs are never registered in ~/.codex/config.toml: Codex reaches
# them through `codex-provider-agent`, which starts an isolated child per
# provider. Composio is the only one that needs a login, and its OAuth grant
# is keyed by the server name and URL in ~/.codex/provider-agents/composio.toml.
#
# Standalone and idempotent — safe to re-run.
###########################################################

COMPOSIO_MCP_URL="https://connect.composio.dev/mcp"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

# Under sudo, $HOME is /root: the login and MCP grant would land in root's
# ~/.codex instead of the user's. pacman is the only step that needs root.
if [ "$(id -u)" -eq 0 ]; then
  echo "ERROR: run codex-setup.sh as your own user, not with sudo; it calls sudo for pacman itself" >&2
  exit 1
fi

###########################################################
# 1. Codex CLI
###########################################################
if ! command -v codex >/dev/null 2>&1; then
  echo "==== Installing Codex CLI ===="
  sudo pacman -S --needed --noconfirm openai-codex
fi

###########################################################
# 2. Stowed configuration
#
# Codex writes /model choices and project trust back into
# config.toml, so it must be the stowed symlink or those
# edits land in an untracked copy.
###########################################################
if [ ! -L "$CODEX_HOME/config.toml" ]; then
  echo "ERROR: $CODEX_HOME/config.toml is not stowed from ~/dotfiles; run 'stow --no-folding --target=\"\$HOME\" --restow codex' in ~/dotfiles first" >&2
  exit 1
fi

###########################################################
# 3. Authenticate (interactive)
#
# ChatGPT sign-in. Business workspaces are supported by the
# official CLI.
###########################################################
if ! codex login status 2>/dev/null | grep -q '^Logged in'; then
  echo "==== Authenticating Codex (interactive) ===="
  codex login
fi

###########################################################
# 4. Composio MCP login (interactive, once)
#
# The server exists only for this command; the isolated
# composio child declares the same name and URL.
###########################################################
composio=(-c "mcp_servers.composio.url=\"$COMPOSIO_MCP_URL\"")
auth_status="$(codex "${composio[@]}" mcp list --json 2>/dev/null |
  jq -r '.[] | select(.name == "composio") | .auth_status' 2>/dev/null || true)"
if [ -z "$auth_status" ] || [ "$auth_status" = "not_logged_in" ]; then
  echo "==== Logging in to the Composio MCP for codex-provider-agent (interactive) ===="
  codex "${composio[@]}" mcp login composio
fi

cat <<'EOF'

==== Codex setup complete ====

One manual step the first time:
  1. Start Codex:            codex
  2. Run inside Codex:       /hooks
  3. Review and trust the stowed hooks (Superpowers session start,
     agent-memory, tmux status). Codex skips hooks until they are trusted.
EOF
