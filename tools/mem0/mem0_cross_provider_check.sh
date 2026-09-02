#!/usr/bin/env bash
set -euo pipefail

# Verifies Hermes, Claude Code, and OpenCode share one Mem0 account.
#
# Primary check is deterministic: store via Hermes's native verbatim tool,
# then confirm visibility via direct API listing (get_all + substring match)
# -- NOT semantic search. Semantic search over a short marker-like string
# competes poorly against a growing pool of related meta-memories (session
# summaries, prior test noise) once the account has real usage history --
# confirmed while building this script: a freshly-stored exact-string memory
# did not appear in the top 20 semantic search results, but was retrievable
# instantly by direct listing/ID. See the implementation plan's "Known
# limitation: app_id scoping" note for the full story.
#
# Secondary check (natural-language recall via each provider's own CLI) is
# included for illustration since it's closer to daily use, but is honestly
# NOT guaranteed to succeed even when the primary check passes -- both
# because of the semantic-ranking issue above, and because OpenCode's and
# Claude Code's shared plugin defaults to project-scoped search (filtered by
# app_id), while Hermes never tags an app_id at all (it has no "project"
# concept), so Hermes-authored facts are invisible to their DEFAULT scope
# unless the query omits app_id entirely -- their own "global" scope option
# currently errors (sends a wildcard app_id that Mem0's API rejects: "filters
# must include at least one positively-scoped entity ID... Wildcards ...
# do not count").

MARKER="MEM0-CHECK-$(date +%Y%m%dT%H%M%S)"
CONTENT="${MARKER}: mem0 cross-provider check"

VENV_PY="${VENV_PY:-$HOME/Proj/linux-setup/tools/mem0/.venv/bin/python}"
MEM0_ENV="${MEM0_ENV:-$HOME/.config/mem0/env}"
SETTLE_SECONDS="${SETTLE_SECONDS:-20}"

log() { printf '[mem0-check] %s\n' "$*"; }
fail() { printf '[mem0-check] FAIL: %s\n' "$*" >&2; }
pass() { printf '[mem0-check] PASS: %s\n' "$*"; }

if [[ -f "$MEM0_ENV" ]]; then
  set -a; source "$MEM0_ENV"; set +a
fi
if [[ -z "${MEM0_API_KEY:-}" ]]; then
  fail "MEM0_API_KEY not set and $MEM0_ENV not found"
  exit 1
fi
if [[ ! -x "$VENV_PY" ]]; then
  fail "$VENV_PY not found -- run: cd ~/Proj/linux-setup/tools/mem0 && python3 -m venv .venv && .venv/bin/pip install mem0ai pytest"
  exit 1
fi

log "storing marker via Hermes (native mem0_add, verbatim): $MARKER"
if ! timeout 120 hermes -z "Use the mem0_add tool to store this exactly, verbatim, no extraction: $CONTENT" >/tmp/mem0-check-store.log 2>&1; then
  fail "could not invoke Hermes to store the marker"
  cat /tmp/mem0-check-store.log
  exit 1
fi

log "waiting ${SETTLE_SECONDS}s for async extraction to settle..."
sleep "$SETTLE_SECONDS"

log "primary check: deterministic visibility via direct API listing (not semantic search)"
FOUND="$("$VENV_PY" -c "
from mem0 import MemoryClient
import os
c = MemoryClient(api_key=os.environ['MEM0_API_KEY'])
items = c.get_all(filters={'user_id': 'alex'}, page_size=200)
items = items.get('results', items) if isinstance(items, dict) else items
hit = any('$MARKER' in (m.get('memory') or '') for m in items)
print('yes' if hit else 'no')
")"

if [[ "$FOUND" == "yes" ]]; then
  pass "marker stored via Hermes and listable under user_id=alex -- the shared account genuinely has it"
else
  fail "marker not found via direct listing -- investigate before trusting anything else (check Task 8 identity alignment first)"
  exit 1
fi

echo
log "secondary check: natural-language recall via each provider's own CLI (illustrative, not guaranteed -- see caveats in this script's header)"
echo

log "OpenCode (explicitly asking for user_id only, no app_id, to avoid the project-scoping gap):"
if timeout 120 opencode run "Use the search_memories tool with only user_id=alex (do not include app_id) to search for $MARKER, tell me exactly what it says" 2>&1 | tee /tmp/mem0-check-opencode.log | grep -qF "$MARKER"; then
  echo "  found it"
else
  echo "  not found via semantic search this time -- see header caveats; does not contradict the PASS above"
fi

echo
log "Claude Code:"
if timeout 120 claude -p "Search my memories for $MARKER and tell me exactly what it says" --allowedTools "mcp__plugin_mem0_mem0__search_memories" 2>&1 | tee /tmp/mem0-check-claude.log | grep -qF "$MARKER"; then
  echo "  found it"
else
  echo "  not found via semantic search this time -- see header caveats; does not contradict the PASS above"
fi

echo
log "done. Marker used: $MARKER (logs in /tmp/mem0-check-*.log)"
