#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT_DIR/clone-repos.sh"
CONTENT="$(cat "$FILE")"

[[ "$CONTENT" == *"firecrawl/firecrawl.git"* ]] || {
  echo "FAIL: firecrawl repo url missing in clone-repos.sh"
  exit 1
}

[[ "$CONTENT" == *"~/Proj/firecrawl"* ]] || {
  echo "FAIL: firecrawl destination ~/Proj/firecrawl missing in clone-repos.sh"
  exit 1
}

echo "PASS: firecrawl clone wireup present"
