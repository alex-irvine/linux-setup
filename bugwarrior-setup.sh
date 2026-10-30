#!/usr/bin/env bash
set -euo pipefail
umask 077

# Installation belongs here; configuration and the ClickUp compatibility
# plugin belong to dotfiles. Never use stow --adopt on an inline API key.
DOTFILES_DIR="${DOTFILES_DIR:-$HOME/dotfiles}"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "ERROR: run bugwarrior-setup.sh as your own user; it uses sudo only for missing packages" >&2
  exit 1
fi

if [[ ! -f "$DOTFILES_DIR/task/.config/bugwarrior/bugwarrior.toml" ||
      ! -f "$DOTFILES_DIR/task/.local/share/bugwarrior-clickup/pyproject.toml" ]]; then
  echo "ERROR: clone or update dotfiles before running bugwarrior-setup.sh" >&2
  exit 1
fi

missing_packages=()
for package in task uv stow; do
  command -v "$package" >/dev/null 2>&1 || missing_packages+=("$package")
done
if (( ${#missing_packages[@]} )); then
  sudo pacman -S --needed --noconfirm "${missing_packages[@]}"
fi

# Python 3.12 and setuptools also support taskw's distutils import. An editable
# install keeps the small priority/status adapter in sync with stowed dotfiles.
uv tool install --python 3.12 --with setuptools \
  --with-editable "$DOTFILES_DIR/task/.local/share/bugwarrior-clickup" \
  'bugwarrior==2.1.0'

interactive=0
if [[ -t 0 ]]; then
  interactive=1
fi
tool_directory="$(uv tool dir)"
"$tool_directory/bugwarrior/bin/python" - "$DOTFILES_DIR" "$interactive" <<'PY'
import getpass
import os
from pathlib import Path
import sys
import tomllib

dotfiles = Path(sys.argv[1]).resolve()
source = dotfiles / "task/.config/bugwarrior/bugwarrior.toml"
live = Path.home() / ".config/bugwarrior/bugwarrior.toml"
secret = Path.home() / ".config/bugwarrior-secrets/clickup-token"
desired = tomllib.loads(source.read_text())


def fail(message):
    sys.exit("ERROR: " + message)


if secret.parent.is_symlink() or secret.is_symlink() or secret.resolve().is_relative_to(dotfiles):
    fail("Bugwarrior credentials must be regular local files outside dotfiles")
secret.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
secret.parent.chmod(0o700)
if secret.exists():
    secret.chmod(0o600)


def save_token(token):
    if secret.exists():
        if secret.read_text().strip() != token:
            fail("a different private ClickUp key already exists; existing files were preserved")
        return
    descriptor = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(token + "\n")


if live.exists() and live.resolve() != source:
    if live.is_symlink():
        fail("Bugwarrior config points elsewhere; existing files were preserved")
    legacy = tomllib.loads(live.read_text())
    token = legacy.get("clickup", {}).get("token", "")
    if not token or (token.startswith("@oracle:") and token != desired["clickup"]["token"]):
        fail("migrate the existing ClickUp credential oracle before stowing; config was preserved")
    legacy["clickup"]["token"] = desired["clickup"]["token"]
    if legacy != desired:
        fail("merge the existing non-secret Bugwarrior settings into dotfiles before stowing; config was preserved")
    if not token.startswith("@oracle:"):
        save_token(token.strip())
    live.unlink()
    print("Moved the inline ClickUp key to a private local file; configuration is ready for Stow.")

if not secret.exists() and sys.argv[2] == "1":
    token = getpass.getpass("ClickUp API key (leave blank to configure later): ").strip()
    if token:
        save_token(token)

if not secret.is_file() or not secret.read_text().strip():
    print("ClickUp API key is unset. Re-run bugwarrior-setup.sh in a terminal to enter it privately.")
PY

stow --dir="$DOTFILES_DIR" --target="$HOME" --no-folding --restow task
echo "Bugwarrior installed and task configuration stowed. Run 'bugwarrior pull', then 'cu' in zsh."
