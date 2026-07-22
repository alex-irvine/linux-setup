# Firecrawl Cloud Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the self-hosted Firecrawl docker-compose stack with Firecrawl's hosted cloud API, decided on measured evidence (the self-hosted instance processed zero requests in its entire lifetime and has had no crash-recovery for 12 days) plus real pricing analysis (Firecrawl's free tier — 1,000 credits/month — comfortably covers this usage pattern).

**Architecture:** `~/.hermes/.env` gains an active `FIRECRAWL_API_KEY` and `FIRECRAWL_API_URL=https://api.firecrawl.dev`, which every firecrawl-* skill and Hermes's `web: backend: firecrawl` already read generically (confirmed — no hardcoded localhost logic). The self-host bring-up logic in `hermes-setup.sh`, the clone entry in `clone-repos.sh`, and the local docker stack are removed/decommissioned. No dotfiles changes needed — `config.yaml`'s `backend: firecrawl` value is unaffected by hosting model.

**Tech Stack:** bash, Docker Compose (removal only), Firecrawl hosted API (`https://api.firecrawl.dev`, `Authorization: Bearer <key>`).

## Global Constraints

- This is a **separate plan from the cross-provider memory design** (`agent-lib/docs/2026-07-21-cross-provider-memory-design.md`) — no technical overlap, evaluated only via the same hosted-vs-self-hosted methodology. Do not merge these.
- The API key is a secret: lives only in `~/.hermes/.env` (gitignored, covered by the working `hermes-backup.timer`), never in any repo.
- Obtaining the API key is a manual, external, human-only step (account signup) — cannot be scripted.
- Destructive local operations (removing the docker stack, deleting `~/Proj/firecrawl`) must be explicit, confirmed steps — never silently bundled into another task.
- `docs-hermes-firecrawl.test.sh`'s existing assertions (`"Runs hermes-setup.sh"`, `"~/Proj/linux-setup/restore-hermes.sh"`, absence of `"~/.hermes/scripts/restore-hermes.sh"`, `"same-host"`) must still all pass — none reference firecrawl specifics directly, so they constrain wording but don't need editing themselves.

---

### Task 1: Obtain and store the Firecrawl API key

**Files:**
- Modify: `~/.hermes/.env` (not in any repo — runtime secrets file)

**Interfaces:**
- Produces: an active `FIRECRAWL_API_KEY=fc-...` and `FIRECRAWL_API_URL=https://api.firecrawl.dev` in `~/.hermes/.env`, which Task 4's verification step depends on.

- [ ] **Step 1: Sign up and get an API key (manual, human-only)**

Go to https://firecrawl.dev/, sign up (or sign in), open the dashboard, and copy your API key (starts with `fc-`). This cannot be automated — no account exists yet to script against.

- [ ] **Step 2: Update `~/.hermes/.env`**

Run (replace `fc-your-key-here` with the real key from Step 1):

```bash
sed -i 's|^# FIRECRAWL_API_KEY=.*|FIRECRAWL_API_KEY=fc-your-key-here|' ~/.hermes/.env
sed -i 's|^FIRECRAWL_API_URL=.*|FIRECRAWL_API_URL=https://api.firecrawl.dev|' ~/.hermes/.env
```

Expected: the file now has an *uncommented* `FIRECRAWL_API_KEY=fc-...` line and `FIRECRAWL_API_URL=https://api.firecrawl.dev`.

- [ ] **Step 3: Verify the values landed correctly (without printing the key)**

Run:
```bash
grep -c '^FIRECRAWL_API_KEY=fc-' ~/.hermes/.env
grep '^FIRECRAWL_API_URL=' ~/.hermes/.env
```
Expected: first command prints `1`; second prints `FIRECRAWL_API_URL=https://api.firecrawl.dev`.

- [ ] **Step 4: Smoke-test the cloud endpoint directly**

Run (uses the key from your shell, never echoes it):
```bash
curl -s -o /tmp/firecrawl-smoke.json -w '%{http_code}\n' \
  -X POST https://api.firecrawl.dev/v1/scrape \
  -H "Authorization: Bearer $(grep '^FIRECRAWL_API_KEY=' ~/.hermes/.env | cut -d= -f2-)" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
cat /tmp/firecrawl-smoke.json | head -c 300; echo
rm -f /tmp/firecrawl-smoke.json
```
Expected: HTTP `200`, and the JSON body contains markdown content from example.com. If `401`, the key wasn't saved correctly — recheck Step 2. This is the first real request this account has ever made — expect it to consume 1 credit, confirming billing/auth actually works end-to-end.

---

### Task 2: Remove the self-host bring-up from `hermes-setup.sh`

**Files:**
- Modify: `~/Proj/linux-setup/hermes-setup.sh`

**Interfaces:**
- Consumes: nothing from Task 1 (this task only removes code).
- Produces: a `hermes-setup.sh` with no `docker`/`FIRECRAWL_DIR` references, which Task 4's test rewrite depends on.

- [ ] **Step 1: Remove the `FIRECRAWL_DIR` variable and the `docker` requirement**

In `hermes-setup.sh`, remove line 5 (`FIRECRAWL_DIR="${FIRECRAWL_DIR:-$HOME/Proj/firecrawl}"`) and remove `ensure_cmd docker` from `main()` (currently the first line of `main()`, right after the `main() {` opening) — nothing else in this script uses docker once the bring-up block below is removed.

- [ ] **Step 2: Remove the entire firecrawl bring-up block from `main()`**

Delete this whole block (currently between `install_hermes_if_missing`/`ensure_cmd hermes` and `build_product_operations`):

```bash
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

  if (cd "$FIRECRAWL_DIR" && docker compose up -d); then
    :
  else
    rc=$?
    err "failed to start Firecrawl docker compose stack"
    err "run: cd \"$FIRECRAWL_DIR\" && docker compose logs"
    exit "$rc"
  fi

```

Also remove the now-unused `ensure_env_key_if_missing` helper function (lines 18-25) — it existed only to build the firecrawl `.env`, and nothing else in this script calls it.

- [ ] **Step 3: Update the final log message**

Change:
```bash
  log "Hermes + Firecrawl setup complete"
```
to:
```bash
  log "Hermes setup complete (Firecrawl via cloud API)"
```

- [ ] **Step 4: Syntax-check**

Run: `bash -n ~/Proj/linux-setup/hermes-setup.sh && echo OK`
Expected: `OK`.

---

### Task 3: Rewrite `hermes-setup.test.sh` for the simplified script

**Files:**
- Modify: `~/Proj/linux-setup/tests/hermes-setup.test.sh`

**Interfaces:**
- Consumes: the simplified `hermes-setup.sh` from Task 2 (no `FIRECRAWL_DIR`, no docker, new log message).
- Produces: a passing test file with no firecrawl/docker assertions.

- [ ] **Step 1: Replace the whole file**

The `test_missing_firecrawl_repo_fails` and `test_compose_failure_prints_logs_remediation` tests are entirely about behavior that no longer exists (delete both). `test_writes_required_env_keys_and_calls_restore` keeps only its product-operations + restore assertions. Replace the full file content with:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/hermes-setup.sh"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

test_builds_product_ops_and_calls_restore() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  : >"$tmp/log"

  mkdir -p "$tmp/bin"
  cat >"$tmp/bin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  cat >"$tmp/restore-hermes.sh" <<'EOF'
#!/usr/bin/env bash
echo "restore-called" >>"$TEST_LOG"
exit 0
EOF
  chmod +x "$tmp/bin/hermes" "$tmp/restore-hermes.sh"

  set +e
  output="$(PATH="$tmp/bin:$PATH" TEST_LOG="$tmp/log" PRODUCT_OPS_DIR="$tmp/po-missing" RESTORE_SCRIPT="$tmp/restore-hermes.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 0 ]]
  grep -q 'restore-called' "$tmp/log"
  # product-operations build step runs (non-fatal when the source dir is absent)
  assert_contains "$output" "product-operations"
  assert_contains "$output" "Hermes setup complete"
  # docker/firecrawl bring-up is gone -- must not appear anywhere in output
  [[ "$output" != *"docker compose"* ]]
  [[ "$output" != *"Firecrawl repo"* ]]
}

test_missing_restore_script_fails() {
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  mkdir -p "$tmp/bin"
  cat >"$tmp/bin/hermes" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$tmp/bin/hermes"

  set +e
  output="$(PATH="$tmp/bin:$PATH" PRODUCT_OPS_DIR="$tmp/po-missing" RESTORE_SCRIPT="$tmp/nope.sh" "$SUT" 2>&1)"
  rc=$?
  set -e

  [[ $rc -eq 1 ]]
  assert_contains "$output" "restore script missing"
}

test_builds_product_ops_and_calls_restore
test_missing_restore_script_fails
echo "PASS: hermes-setup contract tests"
```

- [ ] **Step 2: Run it**

Run: `bash ~/Proj/linux-setup/tests/hermes-setup.test.sh`
Expected: `PASS: hermes-setup contract tests`

---

### Task 4: Remove the firecrawl clone from `clone-repos.sh` and update its test

**Files:**
- Modify: `~/Proj/linux-setup/clone-repos.sh`
- Modify: `~/Proj/linux-setup/tests/clone-repos-firecrawl-wireup.test.sh`

**Interfaces:**
- Produces: `clone-repos.sh` with no firecrawl clone step; a test asserting its intentional absence (regression guard, same pattern already used elsewhere in this codebase for "must NOT reappear" checks).

- [ ] **Step 1: Remove the firecrawl clone block**

In `clone-repos.sh`, remove:
```bash
echo "==== Cloning Firecrawl ===="
clone_or_pull https://github.com/firecrawl/firecrawl.git ~/Proj/firecrawl
```

- [ ] **Step 2: Update the test to assert absence, not presence**

Replace the full content of `clone-repos-firecrawl-wireup.test.sh`:

```bash
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

[[ "$CONTENT" == *"agent-lib.git"* && "$CONTENT" == *"~/Proj/agent-lib"* ]] || {
  echo "FAIL: agent-lib clone wireup missing in clone-repos.sh"
  exit 1
}

echo "PASS: agent-lib clone wireup present; firecrawl clone intentionally absent"
```

- [ ] **Step 3: Run it**

Run: `bash ~/Proj/linux-setup/tests/clone-repos-firecrawl-wireup.test.sh`
Expected: `PASS: agent-lib clone wireup present; firecrawl clone intentionally absent`

---

### Task 5: Update README and run the full test suite

**Files:**
- Modify: `~/Proj/linux-setup/README.md:37`

**Interfaces:**
- Consumes: nothing new.
- Produces: README wording consistent with the cloud-only setup; must keep the exact substring `"Runs hermes-setup.sh"` (asserted by `docs-hermes-firecrawl.test.sh:8`).

- [ ] **Step 1: Update the step-6 description**

Change:
```markdown
6. Runs hermes-setup.sh (Hermes install, Firecrawl self-host bring-up,
   product-operations venv build, restore bootstrap).
```
to:
```markdown
6. Runs hermes-setup.sh (Hermes install, product-operations venv build,
   restore bootstrap). Firecrawl runs on its hosted cloud API — set
   `FIRECRAWL_API_KEY`/`FIRECRAWL_API_URL` in `~/.hermes/.env` (see
   docs/superpowers/plans/2026-07-22-firecrawl-cloud-migration-plan.md).
```

(This preserves the literal substring `"Runs hermes-setup.sh"` required by the existing docs test.)

- [ ] **Step 2: Run the full linux-setup test suite**

Run:
```bash
cd ~/Proj/linux-setup
for t in tests/*.test.sh; do printf '%-45s ' "$(basename "$t"):"; bash "$t" >/dev/null 2>&1 && echo PASS || { echo FAIL; bash "$t"; }; done
```
Expected: every test prints `PASS`, including `docs-hermes-firecrawl.test.sh`, `hermes-setup.test.sh`, and `clone-repos-firecrawl-wireup.test.sh`.

- [ ] **Step 3: Commit**

```bash
cd ~/Proj/linux-setup
git add hermes-setup.sh clone-repos.sh README.md tests/hermes-setup.test.sh tests/clone-repos-firecrawl-wireup.test.sh docs/superpowers/plans/2026-07-22-firecrawl-cloud-migration-plan.md
git commit -m "refactor: migrate Firecrawl from self-hosted to cloud API

Self-hosted instance processed zero requests in its entire lifetime
(created+crashed same day, 2026-07-10, no restart policy, down 12 days
unnoticed) and Firecrawl's free tier (1,000 credits/month) comfortably
covers this usage. Removes the docker-compose bring-up from
hermes-setup.sh and the clone from clone-repos.sh; FIRECRAWL_API_KEY/URL
in ~/.hermes/.env now point at the hosted API instead."
git push
```

---

### Task 6: Decommission the local docker stack (destructive — explicit, not bundled)

**Files:** none (infrastructure only)

**Interfaces:** none.

- [ ] **Step 1: Confirm Task 1's cloud smoke test passed** before touching the local stack — do not proceed if Task 1 Step 4 didn't return `200`.

- [ ] **Step 2: Stop and remove the local containers + volumes**

Run:
```bash
cd ~/Proj/firecrawl
docker compose down -v
```
Expected: all 6 `firecrawl-*` containers and the `fdb-data`/`fdb-cluster-file` volumes are removed. This reclaims disk space; there is nothing in those volumes worth keeping (confirmed: `nuq`/FoundationDB held only empty-queue reconciler state, zero jobs were ever processed).

- [ ] **Step 3: Verify removal**

Run: `docker ps -a --filter "name=firecrawl"`
Expected: empty output.

- [ ] **Step 4: (Optional, your call) remove the local clone**

The directory is no longer needed once the cloud API is configured and `clone-repos.sh` no longer clones it. If you want it gone:
```bash
rm -rf ~/Proj/firecrawl
```
Not required for correctness — leaving it is harmless, just an unused clone.

---

### Task 7: End-to-end verification

**Files:** none.

- [ ] **Step 1: Trigger a real firecrawl-backed request through the actual skill path** (not a bare curl this time)

Ask the agent to run: "scrape https://example.com and show me the title" (invokes the `firecrawl-scrape` skill using `FIRECRAWL_API_URL`/`FIRECRAWL_API_KEY` from `~/.hermes/.env`).
Expected: markdown content returned, no auth/connection errors.

- [ ] **Step 2: Confirm it's hitting the cloud account, not a stale local reference**

Log in to your Firecrawl account at https://firecrawl.dev/ and check the usage/credits view for the request from Step 1.
Expected: at least 2 credits consumed total (1 from Task 1 Step 4, 1 from this step) — confirms real cloud usage, not silently falling back to the (now-removed) local stack.

- [ ] **Step 3: Set a monitoring reminder**

Same discipline as the mem0 design doc: the "fits comfortably in free tier" conclusion is reasoned from zero historical usage + moderate realistic estimates, not measured over a full month. Check the Firecrawl dashboard's credit usage after a few weeks of normal use. If ever exceeded, the escalation path is Hobby ($16/mo, 5,000 credits) before ever reconsidering self-hosting — and self-hosting should only be reconsidered with a backup/restore story designed up front, per the same standard set in the memory design doc.

---

## Self-Review

**Spec coverage:** free-tier check → Task 1 Step 4 + Task 7 (real usage confirms it fits); separate-from-mem0 scope → stated in Global Constraints; remove self-host bring-up → Tasks 2-4; docs → Task 5; safe decommission of local stack → Task 6 (explicit, gated on cloud working first); end-to-end confidence → Task 7. No gaps found.

**Placeholder scan:** no TBD/TODO; every step has literal commands or full file replacements, not descriptions.

**Type/interface consistency:** `hermes-setup.sh`'s final log message (Task 2 Step 3: `"Hermes setup complete"`) matches the test assertion in Task 3 (`assert_contains "$output" "Hermes setup complete"`) and the README wording in Task 5 uses the distinct, separately-asserted substring `"Runs hermes-setup.sh"` — no collision between the two.
