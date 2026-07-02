#!/usr/bin/env bash
set -euo pipefail

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[tailscale] missing required command: $cmd"
    return 1
  fi
}

ensure_tailscaled_active() {
  if systemctl is-active --quiet tailscaled; then
    return 0
  fi

  echo "[tailscale] tailscaled inactive; starting service"
  if ! sudo systemctl enable --now tailscaled >/dev/null 2>&1; then
    echo "[tailscale] failed to start tailscaled"
    echo "[tailscale] debug: sudo journalctl -u tailscaled --no-pager -n 50"
    return 1
  fi
}

tailscale_login_state() {
  local status_out
  status_out="$(tailscale status 2>&1 || true)"
  if [[ "$status_out" == *"Logged out"* ]]; then
    echo "logged_out"
  else
    echo "logged_in"
  fi
}

print_login_next_step() {
  echo "[tailscale] login required"
  echo "[tailscale] next: sudo tailscale up --ssh"
}

print_status_summary() {
  local ip
  ip="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
  echo "[tailscale] ready"
  if [[ -n "$ip" ]]; then
    echo "[tailscale] ipv4: $ip"
  fi
}

main() {
  require_cmd tailscale || exit 1
  require_cmd systemctl || exit 1
  ensure_tailscaled_active || exit 1

  if [[ "$(tailscale_login_state)" == "logged_out" ]]; then
    print_login_next_step
    exit 10
  fi

  print_status_summary
}

main "$@"
