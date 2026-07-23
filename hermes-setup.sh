#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESTORE_SCRIPT="${RESTORE_SCRIPT:-$SCRIPT_DIR/restore-hermes.sh}"

log() { printf '[hermes-setup] %s\n' "$*"; }
err() { printf '[hermes-setup] %s\n' "$*" >&2; }

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "missing required command: $1"
    exit 1
  }
}

install_hermes_if_missing() {
  if command -v hermes >/dev/null 2>&1; then
    return 0
  fi
  ensure_cmd curl
  log "installing Hermes"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
}

# Build the product-operations MCP server venv (authored bot backend housed in
# agent-lib, symlinked to ~/Proj/product-operations by agent-lib/install.sh).
# Idempotent: skips when the venv entry point already exists. POSTGRES_CONNECTION_STRING
# is supplied at runtime via ~/.hermes/.env; migrations apply on MCP startup.
build_product_operations() {
  local po_dir="${PRODUCT_OPS_DIR:-$HOME/Proj/agent-lib/product-operations}"
  if [[ ! -d "$po_dir" ]]; then
    err "product-operations not found at $po_dir (run clone-repos.sh first)"
    return 0
  fi
  if [[ -x "$po_dir/.venv/bin/product-ops-mcp" ]]; then
    log "product-operations venv already built"
    return 0
  fi
  ensure_cmd python3
  log "building product-operations venv at $po_dir"
  (cd "$po_dir" && python3 -m venv .venv && .venv/bin/python -m pip install -e '.[test]')
}

main() {
  install_hermes_if_missing
  ensure_cmd hermes

  build_product_operations

  if [[ -x "$RESTORE_SCRIPT" ]]; then
    "$RESTORE_SCRIPT" --yes
  else
    err "restore script missing or not executable: $RESTORE_SCRIPT"
    exit 1
  fi

  log "Hermes setup complete (Firecrawl via cloud API)"
}

main "$@"
