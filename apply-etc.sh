#!/usr/bin/env bash
# Mirror $SCRIPT_DIR/etc into /etc and reload affected daemons.
# Re-run any time you add or edit a drop-in under etc/.
set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ETC_SRC="$SCRIPT_DIR/etc"

if [ ! -d "$ETC_SRC" ]; then
  echo "No etc/ tree at $ETC_SRC — nothing to do."
  exit 0
fi

declare -A touched=()

while IFS= read -r -d '' src; do
  rel="${src#"$SCRIPT_DIR/"}"            # etc/systemd/logind.conf.d/lid.conf
  dest="/$rel"                            # /etc/systemd/logind.conf.d/lid.conf
  echo "  -> $dest"
  sudo install -Dm644 "$src" "$dest"
  # Track top-level conf.d (or plain conf file) for reload dispatch.
  case "$rel" in
    etc/systemd/logind.conf.d/*)   touched[logind]=1 ;;
    etc/systemd/journald.conf.d/*) touched[journald]=1 ;;
    etc/systemd/sleep.conf.d/*)    touched[sleep]=1 ;;
    etc/systemd/system.conf.d/*)   touched[systemd]=1 ;;
    etc/sysctl.d/*|etc/sysctl.conf) touched[sysctl]=1 ;;
    etc/udev/rules.d/*)            touched[udev]=1 ;;
    etc/modprobe.d/*)              touched[modprobe]=1 ;;
  esac
done < <(find "$ETC_SRC" -type f -print0)

# Reload affected subsystems. SIGHUP = re-read config, does NOT end sessions.
[ -n "${touched[logind]:-}" ]   && sudo systemctl kill -s HUP systemd-logind   || true
[ -n "${touched[journald]:-}" ] && sudo systemctl kill -s HUP systemd-journald || true
[ -n "${touched[systemd]:-}" ]  && sudo systemctl daemon-reexec                || true
[ -n "${touched[sysctl]:-}" ]   && sudo sysctl --system >/dev/null             || true
[ -n "${touched[udev]:-}" ]     && sudo udevadm control --reload               || true
# sleep.conf: re-read on next suspend, no reload needed.
# modprobe.d: applies on next module load / reboot.

echo "Done."
