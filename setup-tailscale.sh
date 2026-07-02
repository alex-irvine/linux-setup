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
  local status_json
  local compact_json
  local status_out

  if status_json="$(tailscale status --json 2>&1)"; then
    compact_json="$status_json"
    compact_json="${compact_json//$'\n'/}"
    compact_json="${compact_json//$'\r'/}"
    compact_json="${compact_json//[[:space:]]/}"

    if [[ "$compact_json" == *'"BackendState":"Running"'* ]]; then
      echo "logged_in"
      return 0
    fi

    if [[ "$compact_json" == *'"BackendState":"NeedsLogin"'* ]]; then
      echo "logged_out"
      return 0
    fi

    echo "unknown"
    return 0
  fi

  if ! status_out="$(tailscale status 2>&1)"; then
    echo "[tailscale] failed to query tailscale status" >&2
    echo "[tailscale] status --json error: $status_json" >&2
    echo "[tailscale] status error: $status_out" >&2
    return 1
  fi

  if [[ "$status_out" == *"Logged out"* ]]; then
    echo "logged_out"
    return 0
  fi

  echo "unknown"
}

print_login_next_step() {
  echo "[tailscale] login required"
  echo "[tailscale] next: sudo tailscale up --ssh"
}

tailscale_ipv4() {
  local ip_out
  ip_out="$(tailscale ip -4 2>/dev/null || true)"
  ip_out="${ip_out%%$'\n'*}"
  if [[ -n "$ip_out" ]]; then
    echo "$ip_out"
    return 0
  fi

  return 1
}

print_status_summary() {
  local ip="$1"
  echo "[tailscale] ready"
  echo "[tailscale] ipv4: $ip"
}

main() {
  local login_state
  local ip

  require_cmd tailscale || exit 1
  require_cmd systemctl || exit 1
  ensure_tailscaled_active || exit 1

  if ! login_state="$(tailscale_login_state)"; then
    exit 1
  fi

  if [[ "$login_state" == "logged_out" ]]; then
    print_login_next_step
    exit 10
  fi

  if [[ "$login_state" != "logged_in" ]]; then
    echo "[tailscale] unable to determine login state"
    exit 1
  fi

  if ! ip="$(tailscale_ipv4)"; then
    echo "[tailscale] logged in but no IPv4 assigned"
    exit 1
  fi

  print_status_summary "$ip"
}

main "$@"
