#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${MEM0_CONFIG_DIR:-$HOME/.config/mem0}"
ENV_FILE="$CONFIG_DIR/env"
HERMES_ENV="${HERMES_ENV:-$HOME/.hermes/.env}"
ZSHRC="${ZSHRC:-$HOME/.zshrc}"
MEM0_USER_ID="${MEM0_USER_ID:-alex}"
HERMES_CMD="${HERMES_CMD:-hermes}"
HERMES_MEM0_JSON="${HERMES_MEM0_JSON:-$HOME/.hermes/mem0.json}"
CLAUDE_CMD="${CLAUDE_CMD:-claude}"
COPILOT_CMD="${COPILOT_CMD:-copilot}"

log() { printf '[mem0-setup] %s\n' "$*"; }
err() { printf '[mem0-setup] %s\n' "$*" >&2; }

ensure_env_key_if_missing() {
  local file="$1" key="$2" value="$3"
  if ! grep -q "^${key}=" "$file" 2>/dev/null; then
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

prompt_for_key() {
  if [[ -n "${MEM0_API_KEY:-}" ]]; then
    printf '%s' "$MEM0_API_KEY"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    err "no MEM0_API_KEY in env and no terminal to prompt on"
    err "re-run with MEM0_API_KEY=m0-... $0, or create $ENV_FILE by hand"
    return 1
  fi
  printf "Mem0 API key (from https://app.mem0.ai/dashboard/api-keys): " >&2
  read -r key
  printf '%s' "$key"
}

ensure_central_key() {
  mkdir -p "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"
  if [[ -f "$ENV_FILE" ]] && grep -q '^MEM0_API_KEY=' "$ENV_FILE"; then
    log "central key already present at $ENV_FILE"
    return 0
  fi
  local key
  key="$(prompt_for_key)" || return 1
  if [[ -z "$key" ]]; then
    err "empty key, aborting"
    return 1
  fi
  printf 'MEM0_API_KEY=%s\n' "$key" >"$ENV_FILE"
  chmod 600 "$ENV_FILE"
  log "wrote central key to $ENV_FILE"
}

ensure_zshrc_export() {
  local marker="# mem0-setup: source central Mem0 key"
  if grep -qF "$marker" "$ZSHRC" 2>/dev/null; then
    log "$ZSHRC already sources mem0 env"
    return 0
  fi
  {
    printf '\n%s\n' "$marker"
    printf '# Central key lives in %s, never in this tracked file.\n' "$ENV_FILE"
    printf '# See linux-setup/mem0-setup.sh.\n'
    printf '[[ -f "%s" ]] && set -a && source "%s" && set +a\n' "$ENV_FILE" "$ENV_FILE"
  } >>"$ZSHRC"
  log "appended mem0 export snippet to $ZSHRC"
}

ensure_hermes_env_key() {
  mkdir -p "$(dirname "$HERMES_ENV")"
  touch "$HERMES_ENV"
  local key
  key="$(grep -m1 '^MEM0_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
  ensure_env_key_if_missing "$HERMES_ENV" "MEM0_API_KEY" "$key"
  log "ensured MEM0_API_KEY in $HERMES_ENV"
}

ensure_hermes_mem0_json() {
  if [[ -f "$HERMES_MEM0_JSON" ]] && grep -qF "\"user_id\": \"$MEM0_USER_ID\"" "$HERMES_MEM0_JSON" 2>/dev/null; then
    log "$HERMES_MEM0_JSON already has user_id=$MEM0_USER_ID"
    return 0
  fi
  mkdir -p "$(dirname "$HERMES_MEM0_JSON")"
  printf '{\n  "mode": "platform",\n  "user_id": "%s"\n}\n' "$MEM0_USER_ID" >"$HERMES_MEM0_JSON"
  log "wrote $HERMES_MEM0_JSON (user_id=$MEM0_USER_ID)"
}

activate_hermes_provider() {
  if ! command -v "$HERMES_CMD" >/dev/null 2>&1; then
    err "hermes not installed yet; run hermes-setup.sh first"
    return 1
  fi
  # Note: this installed Hermes version's `memory setup mem0` subcommand only
  # accepts a bare provider positional (no --mode/--api-key/--user-id flags),
  # despite Mem0's own published docs showing that flag-based invocation --
  # confirmed against `hermes memory setup mem0 --help` during implementation,
  # not assumed from the docs. `config set memory.provider mem0` plus a
  # hand-written mem0.json is the documented "Or manually:" fallback path
  # (see the mem0 plugin's own bundled README.md), and is what actually works
  # on this build.
  "$HERMES_CMD" config set memory.provider mem0
  ensure_hermes_mem0_json
  log "activated Hermes mem0 provider (user_id=$MEM0_USER_ID)"
}

configure_claude_plugin() {
  # Claude Code's marketplace plugin has a required, sensitive `api_key`
  # userConfig field (confirmed by reading the plugin's own manifest,
  # integrations/mem0-plugin/.claude-plugin/plugin.json) -- separate from
  # process env. Shell-env MEM0_API_KEY alone is not enough for Claude
  # Code's plugin the way it is for Hermes and OpenCode's. This is
  # tolerant of claude not being installed yet (claude-setup.sh, which
  # installs the plugin itself, may not have run in every invocation
  # order this script could be called from).
  if ! command -v "$CLAUDE_CMD" >/dev/null 2>&1; then
    log "claude not installed, skipping plugin config"
    return 0
  fi
  local key
  key="$(grep -m1 '^MEM0_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
  "$CLAUDE_CMD" plugin install mem0@mem0-plugins --config "api_key=$key"
  log "configured Claude Code mem0 plugin api_key"
}

configure_copilot_mcp() {
  # GitHub Copilot CLI is a genuine standalone harness (own session loop, own
  # MCP config at ~/.copilot/mcp-config.json) -- rarely used directly here
  # (mostly stitched in as a model backend through OpenCode/Hermes instead),
  # but wired defensively so it isn't a dead end if it ever is used directly.
  # No official Mem0 plugin exists for it (unlike Claude Code/OpenCode), so
  # this is bare MCP registration only -- tools available, no auto-capture
  # hooks and no auto-injected user_id. `copilot mcp add` is NOT idempotent
  # (errors if the name already exists) -- check via `mcp get` first.
  if ! command -v "$COPILOT_CMD" >/dev/null 2>&1; then
    log "copilot not installed, skipping mcp config"
    return 0
  fi
  if "$COPILOT_CMD" mcp get mem0 >/dev/null 2>&1; then
    log "copilot mem0 mcp entry already present"
    return 0
  fi
  local key
  key="$(grep -m1 '^MEM0_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
  "$COPILOT_CMD" mcp add --transport http mem0 "https://mcp.mem0.ai/mcp/" \
    --header "Authorization: Token $key"
  log "registered mem0 MCP server for Copilot CLI"
}

main() {
  ensure_central_key
  ensure_zshrc_export
  ensure_hermes_env_key
  activate_hermes_provider
  configure_claude_plugin
  configure_copilot_mcp
  log "mem0-setup complete"
}

main "$@"
