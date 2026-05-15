#!/usr/bin/env bash
set -e

###########################################################
# Claude Code setup
#
# Installs Claude Code CLI, clones the personal config repo
# into ~/.claude, installs the Dippy PreToolUse hook, and
# registers marketplaces + plugins (rtk, caveman).
#
# Standalone and idempotent — safe to re-run.
###########################################################

DIPPY_DIR="$HOME/.local/share/dippy"

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
# 3. Dippy + rtk (PreToolUse Bash hooks referenced in settings.json)
#
# Dippy: permission gate (no AUR/brew on Arch — install from
# source and symlink onto PATH so the bare `dippy` command in
# settings.json resolves).
# rtk: output compression proxy. Hook config lives in tracked
# settings.json, so we only need the binary here.
###########################################################
echo "==== Installing Dippy ===="
if [ -d "$DIPPY_DIR/.git" ]; then
  git -C "$DIPPY_DIR" pull --ff-only
else
  rm -rf "$DIPPY_DIR"
  git clone https://github.com/ldayton/Dippy.git "$DIPPY_DIR"
fi
mkdir -p "$HOME/.local/bin"
ln -sf "$DIPPY_DIR/bin/dippy-hook" "$HOME/.local/bin/dippy"

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

###########################################################
# 6. Plugins
###########################################################
echo "==== Installing plugins ===="
claude plugin install caveman@caveman || true
claude plugin install claude-hud@claude-hud || true

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
