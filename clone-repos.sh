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

echo "==== Cloning .triage ===="
clone_or_pull https://github.com/alex-irvine/.triage.git ~/Proj/.triage

echo "==== Cloning tmux plugins ===="
clone_or_pull https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
clone_or_pull https://github.com/tmux-plugins/tmux-yank ~/.tmux/plugins/tmux-yank
