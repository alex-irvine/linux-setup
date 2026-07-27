#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/automation-watchdog/automation-watchdog"

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
    printf 'ASSERT FAILED: expected output NOT to contain: %s\n' "$needle"
    printf 'Actual output:\n%s\n' "$haystack"
    return 1
  fi
}

write_jobs_file() {
  local home="$1" body="$2"
  mkdir -p "$home/.hermes/cron"
  printf '{"jobs": [%s], "updated_at": "2026-07-27T00:00:00+00:00"}' "$body" \
    >"$home/.hermes/cron/jobs.json"
}

write_snapshot() {
  local data_dir="$1" body="$2"
  mkdir -p "$data_dir"
  printf '%s' "$body" >"$data_dir/snapshot.json"
}

test_hermes_cron_job_vanished_reports_reconstructed_fix() {
  local tmp home data_dir output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {"job-1": {"name": "hermes-backup-gdrive", "schedule_display": "0 3 * * *", "script": "hermes-backup-gdrive.sh", "no_agent": true}}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_contains "$output" "hermes_cron"
  assert_contains "$output" "vanished"
  assert_contains "$output" 'hermes cron create "0 3 * * *" --name hermes-backup-gdrive --script hermes-backup-gdrive.sh --no-agent'
}

test_hermes_cron_job_failing_reports_last_error() {
  local tmp home data_dir output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"

  write_jobs_file "$home" '{"id": "job-2", "name": "nightly-report", "enabled": true, "state": "scheduled", "schedule": {"kind": "cron", "expr": "0 6 * * *", "display": "0 6 * * *"}, "next_run_at": "2026-07-27T06:00:00+00:00", "last_run_at": "2026-07-26T06:00:00+00:00", "last_status": "error", "last_error": "boom", "script": "nightly.sh", "no_agent": true}'
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_contains "$output" "failing"
  assert_contains "$output" "boom"
}

test_hermes_cron_job_stale_reports_last_run() {
  local tmp home data_dir output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"

  write_jobs_file "$home" '{"id": "job-3", "name": "old-report", "enabled": true, "state": "scheduled", "schedule": {"kind": "cron", "expr": "0 3 * * *", "display": "0 3 * * *"}, "next_run_at": "2026-07-01T03:00:00+00:00", "last_run_at": "2026-06-30T03:00:00+00:00", "last_status": "ok", "last_error": null, "script": "old.sh", "no_agent": true}'
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_contains "$output" "stale"
  assert_contains "$output" "old-report"
}

test_healthy_job_reports_nothing() {
  local tmp home data_dir future output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  mkdir -p "$home"
  future="$(date -u -d '+1 day' '+%Y-%m-%dT%H:%M:%S+00:00')"

  write_jobs_file "$home" "{\"id\": \"job-4\", \"name\": \"healthy-report\", \"enabled\": true, \"state\": \"scheduled\", \"schedule\": {\"kind\": \"cron\", \"expr\": \"0 3 * * *\", \"display\": \"0 3 * * *\"}, \"next_run_at\": \"$future\", \"last_run_at\": \"2026-07-27T03:00:00+00:00\", \"last_status\": \"ok\", \"last_error\": null, \"script\": \"healthy.sh\", \"no_agent\": true}"
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" bash "$SUT" --dry-run)"

  assert_not_contains "$output" "healthy-report"
}

mk_fake_systemctl() {
  local fakebin="$1" mode="$2"
  cat >"$fakebin/systemctl" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "--user" && "\$2" == "list-units" ]]; then
  exit 0
fi
if [[ "\$1" == "--user" && "\$2" == "show" ]]; then
  unit="\$3"
  prop="\${4#--property=}"
  case "$mode:\$unit:\$prop" in
    healthy:hermes-backup.timer:UnitFileState) echo "enabled" ;;
    healthy:hermes-backup.timer:ActiveState) echo "active" ;;
    healthy:hermes-backup.timer:NextElapseUSecRealtime) echo "Tue 2099-01-01 03:15:00 UTC" ;;
    healthy:hermes-backup.service:Result) echo "success" ;;
    disabled:hermes-backup.timer:UnitFileState) echo "disabled" ;;
    disabled:hermes-backup.timer:ActiveState) echo "inactive" ;;
    failing:hermes-backup.timer:UnitFileState) echo "enabled" ;;
    failing:hermes-backup.timer:ActiveState) echo "active" ;;
    failing:hermes-backup.timer:NextElapseUSecRealtime) echo "Tue 2099-01-01 03:15:00 UTC" ;;
    failing:hermes-backup.service:Result) echo "exit-code" ;;
    stale:hermes-backup.timer:UnitFileState) echo "enabled" ;;
    stale:hermes-backup.timer:ActiveState) echo "active" ;;
    stale:hermes-backup.timer:NextElapseUSecRealtime) echo "Tue 2020-01-01 03:15:00 UTC" ;;
    stale:hermes-backup.service:Result) echo "success" ;;
    *:automation-watchdog.timer:UnitFileState) echo "enabled" ;;
    *:automation-watchdog.timer:ActiveState) echo "active" ;;
    *:automation-watchdog.timer:NextElapseUSecRealtime) echo "Tue 2099-01-01 00:00:00 UTC" ;;
    *:automation-watchdog.service:Result) echo "success" ;;
    *) echo "" ;;
  esac
  exit 0
fi
exit 0
EOF
  chmod +x "$fakebin/systemctl"
}

test_systemd_timer_disabled_reports_enable_fix() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "disabled"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "systemd"
  assert_contains "$output" "vanished"
  assert_contains "$output" "systemctl --user enable --now hermes-backup.timer"
}

test_systemd_service_failing_reports_result() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "failing"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "failing"
  assert_contains "$output" "exit-code"
  assert_contains "$output" "journalctl --user -u hermes-backup.service -n 50"
}

test_systemd_timer_stale_next_elapse_reports_stale() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "stale"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_contains "$output" "stale"
  assert_contains "$output" "systemctl --user list-timers hermes-backup.timer"
}

test_systemd_healthy_reports_nothing() {
  local tmp home data_dir fakebin output
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  home="$tmp/home"
  data_dir="$home/.local/share/automation-watchdog"
  fakebin="$tmp/fakebin"
  mkdir -p "$home" "$fakebin"

  write_jobs_file "$home" ""
  write_snapshot "$data_dir" '{"hermes_cron": {}, "systemd": {}}'
  mk_fake_systemctl "$fakebin" "healthy"

  output="$(HOME="$home" WATCHDOG_DATA_DIR="$data_dir" PATH="$fakebin:$PATH" bash "$SUT" --dry-run)"

  assert_not_contains "$output" "systemd"
}

test_hermes_cron_job_vanished_reports_reconstructed_fix
test_hermes_cron_job_failing_reports_last_error
test_hermes_cron_job_stale_reports_last_run
test_healthy_job_reports_nothing
test_systemd_timer_disabled_reports_enable_fix
test_systemd_service_failing_reports_result
test_systemd_timer_stale_next_elapse_reports_stale
test_systemd_healthy_reports_nothing
printf 'PASS: automation-watchdog contract tests\n'
