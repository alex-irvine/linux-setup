#!/usr/bin/env bash
set -euo pipefail

HOST_NAME="${HOSTNAME:-$(hostname)}"
BASE_REMOTE="gdrive:hermes-backups"
DEFAULT_REMOTE="$BASE_REMOTE/$HOST_NAME"
REMOTE=""
ARCHIVE=""
ASSUME_YES=0
DRY_RUN=0
DOWNLOAD_DIR="${HERMES_RESTORE_WORK_DIR:-$HOME/.local/state/hermes-backup/restore}"

usage() {
  cat <<'USAGE'
Usage: restore-hermes.sh [options]

Options:
  --remote <path>    Explicit remote backup folder
  --archive <name>   Explicit archive file name
  --yes              Skip confirmation prompt
  --dry-run          Resolve source/archive but skip import
  -h, --help         Show help
USAGE
}

log() { printf '[restore-hermes] %s\n' "$*"; }
err() { printf '[restore-hermes] %s\n' "$*" >&2; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    err "missing required command: $1"
    exit 1
  }
}

enable_backup_timer() {
  # A systemd user timer owns backup scheduling (persistent; catches up after
  # suspend/resume). Enable it after a successful restore so backups resume
  # without a fresh empty snapshot overwriting prior remote state.
  if ! command -v systemctl >/dev/null 2>&1; then
    log "systemctl unavailable; enable the backup timer manually"
    return 0
  fi
  systemctl --user daemon-reload 2>/dev/null || true
  if systemctl --user enable --now hermes-backup.timer 2>/dev/null; then
    log "enabled Hermes backup timer (systemd)"
  else
    log "could not enable hermes-backup.timer; run: systemctl --user enable --now hermes-backup.timer"
  fi
}

maybe_install_root_gateway() {
  # Mirrors install.sh's own messaging-token check (maybe_start_gateway(),
  # same exact var list) so a restored root/default profile gets its
  # gateway reinstalled automatically — hermes import itself only reminds
  # about *named* profiles, never the root one.
  local env_file="$HOME/.hermes/.env"
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  local var val
  for var in TELEGRAM_BOT_TOKEN DISCORD_BOT_TOKEN SLACK_BOT_TOKEN SLACK_APP_TOKEN WHATSAPP_ENABLED; do
    val="$(grep "^${var}=" "$env_file" 2>/dev/null | cut -d'=' -f2-)" || true
    if [[ -n "$val" && "$val" != "your-token-here" ]]; then
      log "messaging token detected ($var); installing root gateway service"
      hermes gateway install || log "hermes gateway install failed; run it manually: hermes gateway install"
      return 0
    fi
  done
}

latest_archive_in_remote() {
  local remote="$1"
  rclone lsf "$remote" --files-only 2>/dev/null | grep -E '^hermes-.*\.zip$' | sort | tail -n 1 || true
}

resolve_cross_host_remote() {
  local all_archives
  all_archives="$(rclone lsf "$BASE_REMOTE/" -R --files-only 2>/dev/null | grep -E '^[^/]+/hermes-.*\.zip$' | sort -t/ -k2)"
  if [[ -z "$all_archives" ]]; then
    return 1
  fi

  if ((ASSUME_YES == 1)) || ! (: </dev/tty) 2>/dev/null; then
    local newest host_dir archive
    newest="$(printf '%s\n' "$all_archives" | tail -n 1)"
    host_dir="${newest%%/*}"
    archive="${newest#*/}"
    err "auto-selected most recent cross-host backup: $BASE_REMOTE/$host_dir/$archive"
    printf '%s/%s %s\n' "$BASE_REMOTE" "$host_dir" "$archive"
    return 0
  fi

  local dirs
  mapfile -t dirs < <(rclone lsf "$BASE_REMOTE/" --dirs-only 2>/dev/null | sed 's:/$::')
  if ((${#dirs[@]} == 0)); then
    return 1
  fi

  err "No backup found for current hostname path ($DEFAULT_REMOTE)."
  err "Select backup source:"
  local i=1
  for d in "${dirs[@]}"; do
    err "  [$i] $BASE_REMOTE/$d"
    i=$((i + 1))
  done

  printf "Enter selection number: " >/dev/tty
  local selection
  read -r selection </dev/tty
  if ! [[ "$selection" =~ ^[0-9]+$ ]]; then
    err "invalid selection"
    exit 1
  fi

  local idx=$((selection - 1))
  if ((idx < 0 || idx >= ${#dirs[@]})); then
    err "selection out of range"
    exit 1
  fi

  local chosen_dir="$BASE_REMOTE/${dirs[$idx]}"
  local chosen_archive
  chosen_archive="$(latest_archive_in_remote "$chosen_dir")"
  printf '%s %s\n' "$chosen_dir" "$chosen_archive"
}

while (($# > 0)); do
  case "$1" in
    --remote)
      REMOTE="${2:-}"
      shift 2
      ;;
    --archive)
      ARCHIVE="${2:-}"
      shift 2
      ;;
    --yes)
      ASSUME_YES=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      err "unknown option: $1"
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd hermes
require_cmd rclone

if ! rclone listremotes 2>/dev/null | grep -qx 'gdrive:'; then
  err "gdrive remote not configured; skipping restore"
  err "run: rclone config && rclone lsd gdrive:"
  exit 0
fi

if [[ -z "$REMOTE" ]]; then
  REMOTE="$DEFAULT_REMOTE"
fi

if [[ -z "$ARCHIVE" ]]; then
  ARCHIVE="$(latest_archive_in_remote "$REMOTE")"
fi

if [[ -z "$ARCHIVE" && "$REMOTE" == "$DEFAULT_REMOTE" ]]; then
  selected="$(resolve_cross_host_remote || true)"
  if [[ -n "$selected" ]]; then
    REMOTE="${selected% *}"
    ARCHIVE="${selected##* }"
  fi
fi

if [[ -z "$ARCHIVE" ]]; then
  log "no backup archive found; continuing without restore"
  exit 0
fi

mkdir -p "$DOWNLOAD_DIR"
LOCAL_ARCHIVE="$DOWNLOAD_DIR/$ARCHIVE"

log "Selected archive: $REMOTE/$ARCHIVE"
rclone copyto "$REMOTE/$ARCHIVE" "$LOCAL_ARCHIVE"
log "Downloaded to: $LOCAL_ARCHIVE"

if ((DRY_RUN == 1)); then
  log "dry-run: skipping import"
  exit 0
fi

if ((ASSUME_YES != 1)); then
  printf "Restore Hermes from '%s'? Type 'restore' to continue: " "$LOCAL_ARCHIVE"
  read -r reply
  if [[ "$reply" != "restore" ]]; then
    log "restore cancelled"
    exit 0
  fi
fi

hermes import "$LOCAL_ARCHIVE" --force
enable_backup_timer
maybe_install_root_gateway
log "restore complete"
