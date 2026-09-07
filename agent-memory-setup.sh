#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOTFILES="${DOTFILES:-$HOME/dotfiles}"
AGENT_MEMORY_HOME="${AGENT_MEMORY_HOME:-$HOME/.local/share/agent-memory}"
AGENT_MEMORY_VAULT="${AGENT_MEMORY_VAULT:-$HOME/.agents/memory}"
OLLAMA_EMBED_MODEL="${OLLAMA_EMBED_MODEL:-nomic-embed-text}"
PROJECT="${AGENT_MEMORY_PROJECT:-$ROOT/tools/agent-memory}"
MEMORYCTL="$PROJECT/.venv/bin/memoryctl"

die() { printf '[agent-memory-setup] %s\n' "$*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"; }

require uv
require stow
require ollama
test -d "$DOTFILES/agents" || die "missing dotfiles agents package: $DOTFILES/agents"
test -d "$DOTFILES/systemd" || die "missing dotfiles systemd package: $DOTFILES/systemd"

mkdir -p "$HOME/.local/bin" "$HOME/.config/agent-memory" "$AGENT_MEMORY_HOME"
chmod 700 "$HOME/.config/agent-memory" "$AGENT_MEMORY_HOME"

uv sync --locked --project "$PROJECT" || die "locked memoryctl installation failed; run uv sync --locked --project $PROJECT"
test -x "$MEMORYCTL" || die "memoryctl was not installed at $MEMORYCTL"

link_tmp="$HOME/.local/bin/.memoryctl.$$"
ln -s "$MEMORYCTL" "$link_tmp"
mv -Tf "$link_tmp" "$HOME/.local/bin/memoryctl"
test -x "$HOME/.local/bin/memoryctl" || die "memoryctl link is not executable: $HOME/.local/bin/memoryctl"

stow --dir="$DOTFILES" --target="$HOME" --restow agents systemd || die "failed to stow the agents and systemd packages from $DOTFILES"
test -L "$HOME/.agents/memory" || die "canonical vault was not stowed at $HOME/.agents/memory"
if [[ "$AGENT_MEMORY_VAULT" != "$HOME/.agents/memory" ]]; then
  mkdir -p "$AGENT_MEMORY_VAULT"
  chmod 700 "$AGENT_MEMORY_VAULT"
fi
test -d "$AGENT_MEMORY_VAULT" || die "memory vault is unavailable at $AGENT_MEMORY_VAULT"

ollama_models="$(ollama list)" || die "failed to inspect installed Ollama models"
if ! awk -v model="$OLLAMA_EMBED_MODEL" '
  function normalize(name) { sub(/:latest$/, "", name); return name }
  normalize($1) == normalize(model) { found = 1 }
  END { exit !found }
' <<<"$ollama_models"; then
  ollama pull "$OLLAMA_EMBED_MODEL" || die "failed to pull Ollama embedding model: $OLLAMA_EMBED_MODEL"
fi

AGENT_MEMORY_HOME="$AGENT_MEMORY_HOME" AGENT_MEMORY_VAULT="$AGENT_MEMORY_VAULT" \
  "$HOME/.local/bin/memoryctl" rebuild || die "memoryctl rebuild failed; inspect $AGENT_MEMORY_VAULT and $AGENT_MEMORY_HOME"

if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user daemon-reload || die "failed to reload user systemd units"
  systemctl --user enable --now agent-memory-worker.timer || die "failed to enable agent-memory-worker.timer"
fi

printf '[agent-memory-setup] complete: vault=%s state=%s\n' "$AGENT_MEMORY_VAULT" "$AGENT_MEMORY_HOME"
