#!/usr/bin/env bash
set -euo pipefail

# Runs BEFORE opencode-setup.sh and hermes-setup.sh -- both are downstream
# consumers of the credential this script provisions (Hermes reads
# FIRECRAWL_API_KEY/FIRECRAWL_API_URL straight out of ENV_FILE; OpenCode's
# firecrawl-* skills shell out to the `firecrawl` CLI, which authenticates
# via its own stored-credentials file, seeded below). If no key is set yet
# and this is running at an interactive terminal, prompts for one; otherwise
# soft-skips so unattended/automated runs never block. Idempotent either
# way -- safe to skip now and re-run later once you have a key.
ENV_FILE="${FIRECRAWL_ENV_FILE:-$HOME/.hermes/.env}"

log() { printf '[firecrawl-setup] %s\n' "$*"; }
err() { printf '[firecrawl-setup] %s\n' "$*" >&2; }

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
  grep -q "^${key}=" "$file" 2>/dev/null || printf '%s=%s\n' "$key" "$value" >>"$file"
}

read_env_key() {
  local file="$1"
  local key="$2"
  # `|| true`: grep exits 1 on "no match" (the expected case when the key
  # isn't set yet), which pipefail would otherwise propagate and, under
  # set -e, kill the whole script right when it needs to soft-skip instead.
  grep "^${key}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

# Removes any existing line for $key (commented placeholder or live value)
# and appends a fresh one. Deliberately not sed-based: the value is a
# secret the user just typed, and sed substitution treats it as a
# pattern/replacement (breaks on &, |, \). Here it's only ever interpolated
# via printf '%s', so no characters need escaping.
set_env_key() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp)"
  grep -v -E "^#? ?${key}=" "$file" 2>/dev/null >"$tmp" || true
  printf '%s=%s\n' "$key" "$value" >>"$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
}

# Overridable for tests, which have no real controlling terminal:
# FIRECRAWL_SETUP_INTERACTIVE unset -> real `-t 0` check (production
# default, zero config). Set to "1"/"0" to force the answer either way.
is_interactive() {
  if [[ -n "${FIRECRAWL_SETUP_INTERACTIVE:-}" ]]; then
    [[ "$FIRECRAWL_SETUP_INTERACTIVE" == "1" ]]
    return
  fi
  [[ -t 0 ]]
}

main() {
  ensure_cmd npm

  # Safe to create ENV_FILE before Hermes itself is installed: Hermes's own
  # installer only writes it `if [ ! -f "$HERMES_HOME/.env" ]`, and logs
  # "~/.hermes/.env already exists, keeping it" otherwise -- confirmed
  # non-destructive, never clobbers a pre-existing file.
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  ensure_env_key_if_missing "$ENV_FILE" "FIRECRAWL_API_URL" "https://api.firecrawl.dev"

  if ! command -v firecrawl >/dev/null 2>&1; then
    log "installing firecrawl-cli"
    npm install -g firecrawl-cli
  fi

  local key
  key="$(read_env_key "$ENV_FILE" "FIRECRAWL_API_KEY")"

  if [[ -z "$key" ]] && is_interactive; then
    log "no FIRECRAWL_API_KEY set in $ENV_FILE yet"
    printf '[firecrawl-setup] Enter your Firecrawl API key (https://firecrawl.dev/, blank to skip for now): ' >&2
    read -r -s key
    echo >&2
    if [[ -n "$key" ]]; then
      set_env_key "$ENV_FILE" "FIRECRAWL_API_KEY" "$key"
      log "saved FIRECRAWL_API_KEY to $ENV_FILE"
    fi
  fi

  if [[ -z "$key" ]]; then
    grep -q '^# FIRECRAWL_API_KEY=' "$ENV_FILE" 2>/dev/null || printf '# FIRECRAWL_API_KEY=fc-your-key-here\n' >>"$ENV_FILE"
    log "no FIRECRAWL_API_KEY set in $ENV_FILE yet"
    log "sign up at https://firecrawl.dev/, then re-run this script (prompts for it"
    log "interactively), or uncomment and set it in $ENV_FILE by hand"
    log "firecrawl-cli installed; keyless free tier active until then (rate-limited)"
    return 0
  fi

  log "seeding firecrawl-cli stored credentials from $ENV_FILE"
  firecrawl login --api-key "$key" >/dev/null

  log "firecrawl-setup complete (Hermes reads $ENV_FILE directly; OpenCode's firecrawl-* skills use the CLI's stored credentials just seeded)"
}

main "$@"
