#!/usr/bin/env bash
set -euo pipefail

###########################################################
# Claude Code setup
#
# Installs Claude Code CLI, rtk, and registers marketplaces +
# plugins (caveman, claude-hud).
#
# ~/.claude settings, agents, and commands come from the `claude` Stow package
# in ~/dotfiles. They are applied by endeavouros-setup.sh; run that first.
#
# Standalone and idempotent — safe to re-run.
###########################################################

###########################################################
# 1. Claude Code CLI
#
# ~/.claude/settings.json is stowed from the dotfiles repo
# by endeavouros-setup.sh — run that first.
###########################################################
if ! command -v claude >/dev/null 2>&1; then
  echo "==== Installing Claude Code ===="
  curl -fsSL https://claude.ai/install.sh | bash
fi

###########################################################
# 2. TMPDIR workaround
#
# Plugin install copies across filesystems and fails on Linux
# because /tmp is tmpfs:
#   EXDEV: cross-device link not permitted
# See https://github.com/anthropics/claude-code/issues/14799
###########################################################
mkdir -p "$HOME/.cache/tmp"
if ! grep -q 'TMPDIR=' "$HOME/.zshrc" 2>/dev/null; then
  echo 'export TMPDIR="$HOME/.cache/tmp"' >>"$HOME/.zshrc"
fi
export TMPDIR="$HOME/.cache/tmp"

###########################################################
# 3. rtk (PreToolUse Bash hook referenced in settings.json)
#
# Output compression proxy. Hook config lives in tracked
# settings.json, so we only need the binary here.
###########################################################
echo "==== Installing rtk ===="
if ! command -v rtk >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
fi

###########################################################
# 4. Authenticate (interactive)
#
# `claude plugin` commands need a logged-in session. If
# ~/.claude/.credentials.json is missing, drop into Claude
# so the user can sign in; otherwise skip.
###########################################################
if [ ! -f "$HOME/.claude/.credentials.json" ]; then
  echo "==== Authenticating Claude Code (interactive) ===="
  echo "Sign in, then type /exit to continue."
  claude
fi

###########################################################
# 5. Marketplaces
###########################################################
echo "==== Registering marketplaces ===="
claude plugin marketplace add anthropics/claude-plugins-official || true
claude plugin marketplace add JuliusBrussee/caveman || true
claude plugin marketplace add jarrodwatts/claude-hud || true
claude plugin marketplace add mem0ai/mem0 || true

###########################################################
# 6. Plugins
###########################################################
echo "==== Installing plugins ===="
claude plugin install caveman@caveman || true
claude plugin install claude-hud@claude-hud || true
claude plugin install mem0@mem0-plugins || true

###########################################################
# 6. MCP
###########################################################
remove_mcp_if_present() {
  local server="$1" result
  if result="$(claude mcp get "$server" 2>&1)"; then
    claude mcp remove --scope user "$server"
  else
    case "$result" in
      "No MCP server named \"$server\"."*) ;;
      *) printf '%s\n' "$result" >&2; echo "ERROR: unable to verify Claude MCP '$server'" >&2; exit 1 ;;
    esac
  fi
}

add_http_mcp_if_missing() {
  local server="$1" url result
  url="$2"
  if result="$(claude mcp get "$server" 2>&1)"; then
    return 0
  fi
  case "$result" in
    "No MCP server named \"$server\"."*) claude mcp add --transport http -s user "$server" "$url" ;;
    *) printf '%s\n' "$result" >&2; echo "ERROR: unable to verify Claude MCP '$server'" >&2; exit 1 ;;
  esac
}

remove_mcp_if_present chrome-devtools
remove_mcp_if_present playwright
add_http_mcp_if_missing betterstack https://mcp.betterstack.com
add_http_mcp_if_missing composio https://connect.composio.dev/mcp

cat <<'EOF'

==== Claude setup complete ====

One manual step the first time you set up claude-hud:
  1. Start Claude:           claude
  2. Run inside Claude:      /claude-hud:setup
  3. Restart Claude Code.    The HUD will appear below your input.

This writes a statusLine block into ~/.claude/settings.json. Since
that file is tracked, commit + push afterwards and future fresh
installs will inherit the HUD config automatically.
EOF

cat <<'EOF'

One manual step the first time you set up mem0:
  1. Start Claude:           claude
  2. Run inside Claude:      /mem0:onboard
  3. Follow the prompts.     Verifies the API key, imports CLAUDE.md/AGENTS.md,
                             and shows your identity (user ID, project scope).

Compare the reported user ID against OpenCode's (/mem0-status) and Hermes's
(~/.hermes/mem0.json user_id) — see Task 8 of the cross-provider memory plan.
EOF
