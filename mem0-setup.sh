#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${MEM0_CONFIG_DIR:-$HOME/.config/mem0}"
ENV_FILE="$CONFIG_DIR/env"
HERMES_ENV="${HERMES_ENV:-$HOME/.hermes/.env}"
ZSHRC="${ZSHRC:-$HOME/.zshrc}"
MEM0_USER_ID="${MEM0_USER_ID:-alex}"
HERMES_CMD="${HERMES_CMD:-hermes}"

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

activate_hermes_provider() {
  if ! command -v "$HERMES_CMD" >/dev/null 2>&1; then
    err "hermes not installed yet; run hermes-setup.sh first"
    return 1
  fi
  local key
  key="$(grep -m1 '^MEM0_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
  "$HERMES_CMD" memory setup mem0 --mode platform --api-key "$key" --user-id "$MEM0_USER_ID"
  log "activated Hermes mem0 provider (user_id=$MEM0_USER_ID)"
}

main() {
  ensure_central_key
  ensure_zshrc_export
  ensure_hermes_env_key
  activate_hermes_provider
  log "mem0-setup complete"
}

main "$@"
