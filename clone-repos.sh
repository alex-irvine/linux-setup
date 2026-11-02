#!/usr/bin/env bash
set -e

###########################################################
# Repo clones
#
# Runs after `gh auth login` in endeavouros-setup.sh, so
# private clones over https work via the gh credential helper.
# Runs BEFORE stow, because some repos (e.g. .triage) are the
# stow target for files held in ~/dotfiles.
#
# Idempotent — re-runs pull --ff-only on existing repos.
###########################################################

clone_or_pull() {
  local url=$1
  local dest=$2
  if [ ! -d "$dest/.git" ]; then
    mkdir -p "$(dirname "$dest")"
    git clone "$url" "$dest"
  else
    git -C "$dest" pull --ff-only || true
  fi
}

echo "==== Cloning dotfiles ===="
clone_or_pull https://github.com/alex-irvine/dotfiles.git ~/dotfiles

echo "==== Cloning Superpowers skills ===="
# Dotfiles stows directory links into this checkout. Clone it before Stow;
# its installer is for standalone users and would compete with Stow ownership.
clone_or_pull https://github.com/datascopesystems/super-mezzanine.git ~/Proj/super-mezzanine
if [ ! -r "$HOME/Proj/super-mezzanine/skills/using-superpowers/SKILL.md" ] ||
   [ ! -r "$HOME/Proj/super-mezzanine/runtimes/opencode/agents/superpowers.md" ]; then
  echo "ERROR: Superpowers checkout is incomplete; refusing to continue to Stow" >&2
  exit 1
fi

echo "==== Cloning .triage ===="
clone_or_pull https://github.com/alex-irvine/.triage.git ~/Proj/.triage

echo "==== Cloning hermes-bots ===="
# Hermes-specific bots and automation. Provider-visible skills and adapters are
# stowed from dotfiles; non-Stowable bot runtime is installed below.
clone_or_pull https://github.com/alex-irvine/hermes-bots.git ~/Proj/hermes-bots

echo "==== Cloning tmux plugins ===="
clone_or_pull https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
clone_or_pull https://github.com/tmux-plugins/tmux-yank ~/.tmux/plugins/tmux-yank
