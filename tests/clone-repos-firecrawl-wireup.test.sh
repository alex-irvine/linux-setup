#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/clone-repos.sh"
CONTENT="$(cat "$FILE")"

# Firecrawl migrated to the hosted cloud API (2026-07-22) -- must NOT be
# cloned/self-hosted again without revisiting that decision.
[[ "$CONTENT" != *"firecrawl/firecrawl.git"* ]] || {
  echo "FAIL: firecrawl clone re-added to clone-repos.sh -- see docs/superpowers/plans/2026-07-22-firecrawl-cloud-migration-plan.md"
  exit 1
}

[[ "$CONTENT" == *"hermes-bots.git"* && "$CONTENT" == *"~/Proj/hermes-bots"* ]] || {
  echo "FAIL: hermes-bots clone wireup missing in clone-repos.sh"
  exit 1
}

echo "PASS: hermes-bots clone wireup present; firecrawl clone intentionally absent"
