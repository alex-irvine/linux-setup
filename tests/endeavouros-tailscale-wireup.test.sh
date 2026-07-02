#!/usr/bin/env bash
set -euo pipefail

FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/endeavouros-setup.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *"tailscale"* ]] || { echo "FAIL: tailscale package install missing"; exit 1; }
[[ "$CONTENT" == *"setup-tailscale.sh"* ]] || { echo "FAIL: setup-tailscale.sh call missing"; exit 1; }

echo "PASS: tailscale wireup present"
