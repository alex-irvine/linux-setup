#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRECRAWL_DIR="${FIRECRAWL_DIR:-$HOME/Proj/firecrawl}"
RESTORE_SCRIPT="${RESTORE_SCRIPT:-$SCRIPT_DIR/restore-hermes.sh}"

log() { printf '[hermes-setup] %s\n' "$*"; }
err() { printf '[hermes-setup] %s\n' "$*" >&2; }

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "missing required command: $1"
    exit 1
  }
}

ensure_env_key_if_missing() {
  local file="$1"
  local key="$2"
  local value="$3"
  if ! grep -q "^${key}=" "$file"; then
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

install_hermes_if_missing() {
  if command -v hermes >/dev/null 2>&1; then
    return 0
  fi
  ensure_cmd curl
  log "installing Hermes"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
}

main() {
  ensure_cmd docker

  install_hermes_if_missing
  ensure_cmd hermes

  if [[ ! -d "$FIRECRAWL_DIR" ]]; then
    err "missing Firecrawl repo at: $FIRECRAWL_DIR"
    err "run clone-repos.sh or full bootstrap first"
    exit 1
  fi

  mkdir -p "$FIRECRAWL_DIR"
  : >"$FIRECRAWL_DIR/.env.tmp"
  if [[ -f "$FIRECRAWL_DIR/.env" ]]; then
    cat "$FIRECRAWL_DIR/.env" >"$FIRECRAWL_DIR/.env.tmp"
  fi

  ensure_env_key_if_missing "$FIRECRAWL_DIR/.env.tmp" "PORT" "3002"
  ensure_env_key_if_missing "$FIRECRAWL_DIR/.env.tmp" "HOST" "0.0.0.0"
  ensure_env_key_if_missing "$FIRECRAWL_DIR/.env.tmp" "USE_DB_AUTHENTICATION" "false"
  if ! grep -q '^BULL_AUTH_KEY=' "$FIRECRAWL_DIR/.env.tmp"; then
    ensure_cmd openssl
    printf 'BULL_AUTH_KEY=%s\n' "$(openssl rand -hex 16)" >>"$FIRECRAWL_DIR/.env.tmp"
  fi
  mv "$FIRECRAWL_DIR/.env.tmp" "$FIRECRAWL_DIR/.env"

  (cd "$FIRECRAWL_DIR" && docker compose up -d)

  if [[ -x "$RESTORE_SCRIPT" ]]; then
    "$RESTORE_SCRIPT" --yes
  else
    err "restore script missing or not executable: $RESTORE_SCRIPT"
    exit 1
  fi

  log "Hermes + Firecrawl setup complete"
}

main "$@"
