#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/alarm/alarm"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'ASSERT FAILED: expected output to NOT contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

setup_fake_commands() {
  local fakebin="$1"

  cat >"$fakebin/at" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state_dir="${ALARM_TEST_STATE_DIR:?}"
jobs_file="$state_dir/jobs"
next_file="$state_dir/next_job"
last_command_file="$state_dir/last_command"

mkdir -p "$state_dir"
[[ -f "$next_file" ]] || printf '100\n' >"$next_file"

if [[ "${ALARM_TEST_AT_FAIL:-0}" == "1" ]]; then
  echo "at: scheduler failure" >&2
  exit 1
fi

cat >"$last_command_file"
job_id="$(cat "$next_file")"
printf '%s\n' "$((job_id + 1))" >"$next_file"
printf '%s\n' "$job_id" >>"$jobs_file"
echo "job $job_id at Fri Jan 01 00:00:00 2038" >&2
EOF

  cat >"$fakebin/atq" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state_dir="${ALARM_TEST_STATE_DIR:?}"
jobs_file="$state_dir/jobs"

if [[ -f "$jobs_file" ]]; then
  while IFS= read -r job_id; do
    [[ -n "$job_id" ]] || continue
    printf '%s\tFri Jan 01 00:00:00 2038\n' "$job_id"
  done <"$jobs_file"
fi
EOF

  cat >"$fakebin/atrm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state_dir="${ALARM_TEST_STATE_DIR:?}"
jobs_file="$state_dir/jobs"
job_id="${1:-}"

[[ -n "$job_id" ]] || exit 1
[[ -f "$jobs_file" ]] || exit 1

if grep -Fxq "$job_id" "$jobs_file"; then
  tmp="$(mktemp)"
  grep -Fxv "$job_id" "$jobs_file" >"$tmp" || true
  mv "$tmp" "$jobs_file"
  exit 0
fi

echo "atrm: job not found" >&2
exit 1
EOF

  chmod +x "$fakebin/at" "$fakebin/atq" "$fakebin/atrm"
}

make_env() {
  local root
  root="$(mktemp -d)"
  local home="$root/home"
  local state="$root/state"
  local fakebin="$root/fakebin"

  mkdir -p "$home" "$state" "$fakebin"
  setup_fake_commands "$fakebin"

  printf '%s\n%s\n%s\n' "$home" "$state" "$fakebin"
}

run_alarm() {
  local home="$1"
  local state="$2"
  local fakebin="$3"
  shift 3

  HOME="$home" \
  PATH="$fakebin:$PATH" \
  ALARM_TEST_STATE_DIR="$state" \
  ALARM_DATA_DIR="$home/.local/share/alarm-cli" \
  bash "$SUT" "$@"
}

test_add_absolute_and_list() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  set +e
  output="$(run_alarm "$home" "$state" "$fakebin" add "2030-01-01 07:30" "Gym" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 0 ]]
  assert_contains "$output" "added alarm 1"

  output="$(cat "$state/last_command")"
  assert_contains "$output" "alarm-trigger"

  output="$(run_alarm "$home" "$state" "$fakebin" list 2>&1)"
  assert_contains "$output" "Gym"
  assert_contains "$output" "scheduled"
}

test_add_relative_and_list() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  set +e
  output="$(run_alarm "$home" "$state" "$fakebin" add --in 45m "Tea" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 0 ]]
  assert_contains "$output" "added alarm 1"

  output="$(run_alarm "$home" "$state" "$fakebin" list 2>&1)"
  assert_contains "$output" "Tea"
  assert_contains "$output" "scheduled"
}

test_delete_removes_alarm() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  run_alarm "$home" "$state" "$fakebin" add "2030-01-01 07:30" "DeleteMe" >/dev/null

  output="$(run_alarm "$home" "$state" "$fakebin" delete 1 2>&1)"
  assert_contains "$output" "deleted alarm 1"

  output="$(run_alarm "$home" "$state" "$fakebin" list 2>&1)"
  assert_not_contains "$output" "DeleteMe"
  assert_contains "$output" "no alarms"
}

test_invalid_time_returns_2() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  set +e
  output="$(run_alarm "$home" "$state" "$fakebin" add "not-a-time" "Bad" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 2 ]]
  assert_contains "$output" "invalid datetime"
}

test_scheduler_failure_does_not_write_metadata() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  set +e
  output="$(ALARM_TEST_AT_FAIL=1 run_alarm "$home" "$state" "$fakebin" add "2030-01-01 07:30" "Fail" 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 1 ]]
  assert_contains "$output" "failed to schedule alarm"

  output="$(run_alarm "$home" "$state" "$fakebin" list 2>&1)"
  assert_contains "$output" "no alarms"
}

test_delete_unknown_id_returns_2() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  set +e
  output="$(run_alarm "$home" "$state" "$fakebin" delete 99 2>&1)"
  local exit_code=$?
  set -e

  [[ $exit_code -eq 2 ]]
  assert_contains "$output" "unknown alarm id: 99"
  assert_contains "$output" "run 'alarm list'"
}

test_list_marks_stale_alarm() {
  local env_out home state fakebin output
  env_out="$(make_env)"
  home="$(printf '%s\n' "$env_out" | sed -n '1p')"
  state="$(printf '%s\n' "$env_out" | sed -n '2p')"
  fakebin="$(printf '%s\n' "$env_out" | sed -n '3p')"

  run_alarm "$home" "$state" "$fakebin" add "2030-01-01 07:30" "StaleMe" >/dev/null
  : >"$state/jobs"

  output="$(run_alarm "$home" "$state" "$fakebin" list 2>&1)"
  assert_contains "$output" "StaleMe"
  assert_contains "$output" "stale"
}

test_add_absolute_and_list
test_add_relative_and_list
test_delete_removes_alarm
test_invalid_time_returns_2
test_scheduler_failure_does_not_write_metadata
test_delete_unknown_id_returns_2
test_list_marks_stale_alarm

printf 'PASS: alarm CLI contract tests\n'
