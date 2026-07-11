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

latest_archive_in_remote() {
  local remote="$1"
  rclone lsf "$remote" --files-only 2>/dev/null | grep -E '^hermes-.*\.zip$' | sort | tail -n 1 || true
}

prompt_for_remote_dir() {
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

  printf "Enter selection number: " >&2
  read -r selection
  if ! [[ "$selection" =~ ^[0-9]+$ ]]; then
    err "invalid selection"
    exit 1
  fi

  local idx=$((selection - 1))
  if ((idx < 0 || idx >= ${#dirs[@]})); then
    err "selection out of range"
    exit 1
  fi

  printf '%s/%s\n' "$BASE_REMOTE" "${dirs[$idx]}"
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
  selected_remote="$(prompt_for_remote_dir || true)"
  if [[ -n "$selected_remote" ]]; then
    REMOTE="$selected_remote"
    ARCHIVE="$(latest_archive_in_remote "$REMOTE")"
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
log "restore complete"
