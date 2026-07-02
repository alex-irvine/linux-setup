#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAIL_DOC="$ROOT_DIR/TAILSCALE.md"
README="$ROOT_DIR/README.md"

[[ -f "$TAIL_DOC" ]] || { echo "FAIL: missing TAILSCALE.md"; exit 1; }

TAIL_CONTENT="$(cat "$TAIL_DOC")"
README_CONTENT="$(cat "$README")"

[[ "$TAIL_CONTENT" == *"## Mobile apps (manual install)"* ]] || { echo "FAIL: missing mobile apps section"; exit 1; }
[[ "$TAIL_CONTENT" == *"Tailscale"* ]] || { echo "FAIL: missing Tailscale app mention"; exit 1; }
[[ "$TAIL_CONTENT" == *"SSH"* ]] || { echo "FAIL: missing SSH app mention"; exit 1; }
[[ "$TAIL_CONTENT" == *"## Lost device response"* ]] || { echo "FAIL: missing lost-device section"; exit 1; }
[[ "$TAIL_CONTENT" == *"Preferred auth posture: Tailscale SSH policy-managed access."* ]] || { echo "FAIL: missing preferred auth posture"; exit 1; }
[[ "$TAIL_CONTENT" == *"Fallback: OpenSSH over tailnet with key-based auth only."* ]] || { echo "FAIL: missing OpenSSH fallback posture"; exit 1; }
[[ "$README_CONTENT" == *"Remote tmux via Tailscale"* ]] || { echo "FAIL: README missing remote tmux section"; exit 1; }
[[ "$README_CONTENT" == *"TAILSCALE.md"* ]] || { echo "FAIL: README missing TAILSCALE.md link"; exit 1; }

echo "PASS: docs contract checks"
