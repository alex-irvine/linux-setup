#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

###########################################################
# EndeavourOS / Arch setup script
###########################################################

echo "==== Updating system ===="
sudo pacman -Syu --noconfirm

echo "==== Installing base tools ===="
sudo pacman -S --noconfirm --needed \
  base-devel curl wget gnupg ca-certificates unzip clang pkgconf git github-cli

###########################################################
# GitHub CLI auth — must happen BEFORE the dotfiles clone
# because dotfiles is a private repo. `gh auth login` wires
# `gh auth git-credential` as the git credential helper, so
# subsequent https clones of private repos succeed.
###########################################################
echo "==== GitHub CLI Authentication ===="
if ! gh auth status >/dev/null 2>&1; then
  echo "Authenticate now — required for private dotfiles clone + lazyorc/lazyfleet."
  gh auth login --git-protocol https --hostname github.com
fi
gh auth setup-git
if ! gh auth status 2>&1 | grep -q 'read:packages'; then
  gh auth refresh -s read:packages
fi

if ! grep -q '^fs.inotify.max_user_watches=' /etc/sysctl.conf; then
  echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
fi
if ! grep -q '^fs.inotify.max_user_instances=' /etc/sysctl.conf; then
  echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
fi

sudo pacman -S --noconfirm --needed \
  sway waybar wofi foot mako swaylock swayidle xorg-xwayland \
  wl-clipboard pipewire pipewire-pulse wireplumber pulsemixer \
  bluez bluez-utils network-manager-applet pulsemixer stow \
  grim slurp satty task swaybg

###########################################################
# System config drop-ins (/etc/*)
#
# Source-of-truth files live under $SCRIPT_DIR/etc and mirror
# the real /etc tree. Add new files there and re-run
# apply-etc.sh (or this script) to install them.
###########################################################
echo "==== Installing /etc drop-ins ===="
bash "$SCRIPT_DIR/apply-etc.sh"

###########################################################
# Repo clones (dotfiles, .triage, tmux plugins)
#
# Lives in clone-repos.sh so a fresh OS install is one
# `bash clone-repos.sh` away from being personalised. Must
# run AFTER `gh auth login` above (private dotfiles repo)
# and BEFORE stow below (stow needs target dirs cloned).
###########################################################
echo "==== Cloning repos ===="
bash "$SCRIPT_DIR/clone-repos.sh"

echo "==== Clearing default configs that conflict with stow ===="
# sway/foot/mako/nvim auto-create config dirs on first launch; clear
# them so stow can take over. Also drop the stale per-tool config
# files at $HOME root. Skip anything already symlinked (re-run safe).
for d in ~/.config/sway ~/.config/mako ~/.config/foot \
         ~/.config/nvim ~/.config/tmuxinator \
         ~/.config/gtk-3.0 ~/.config/gtk-4.0 \
         ~/.config/evolution/sources ~/.config/evolution/signatures \
         ~/.config/evolution/mail/folders ~/.config/evolution/mail/views; do
  [ -L "$d" ] || rm -rf "$d"
done
for f in ~/.zshrc ~/.tmux.conf ~/.taskrc \
         ~/.config/evolution/mail/state.ini; do
  [ -L "$f" ] || rm -f "$f"
done

echo "==== Stowing dotfiles ===="
cd ~/dotfiles
stow --target="$HOME" --restow claude evolution foot gtk mako nvim sway systemd task tmux tmuxinator triage waybar zsh
cd -

echo "==== Setting dark color-scheme (dconf) ===="
gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark' || true
gsettings set org.gnome.desktop.interface gtk-theme 'Adwaita-dark' || true

###########################################################
# yay (AUR helper)
###########################################################
if ! command -v yay >/dev/null 2>&1; then
  echo "==== Installing yay (AUR helper) ===="
  TMP_YAY="/tmp/yay-build"
  rm -rf "$TMP_YAY"
  git clone https://aur.archlinux.org/yay.git "$TMP_YAY"
  (cd "$TMP_YAY" && makepkg -si --noconfirm)
  rm -rf "$TMP_YAY"
fi


###########################################################
# yay utils
###########################################################
echo "==== Installing yay utils ===="
yay -S --noconfirm --needed bluetuith wl-clip-persist

###########################################################
# Golang
###########################################################
echo "==== Installing golang ===="
sudo pacman -S --noconfirm --needed go

###########################################################
# .NET SDK
# Host SDK powers nvim LSP (Roslyn) navigation/analysis across all repos.
# Latest SDK builds older target frameworks (net7-net10); global.json pins
# use rollForward: latestMajor so they roll up to it. Dev containers still
# own run/debug per project's dotnet version. aspnet-runtime for web projects.
###########################################################
echo "==== Installing .NET SDK ===="
sudo pacman -S --noconfirm --needed dotnet-sdk aspnet-runtime

###########################################################
# Node.js + npm
###########################################################
echo "==== Installing Node.js + npm ===="
sudo pacman -S --noconfirm --needed nodejs npm

###########################################################
# Neovim
###########################################################
echo "==== Installing Neovim ===="
sudo pacman -S --noconfirm --needed neovim

echo "==== Installing Nerd Fonts ===="
mkdir -p ~/.local/share/fonts

if [ ! -d ~/.local/share/fonts/JetBrainsMono ] || [ -z "$(ls -A ~/.local/share/fonts/JetBrainsMono 2>/dev/null)" ]; then
  JBM_TEMP="/tmp/JetBrainsMono.zip"
  curl -fLo "$JBM_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/JetBrainsMono.zip
  mkdir -p ~/.local/share/fonts/JetBrainsMono
  unzip -o "$JBM_TEMP" -d ~/.local/share/fonts/JetBrainsMono
  rm "$JBM_TEMP"
fi

if ! ls ~/.local/share/fonts/SymbolsNerdFont*.ttf >/dev/null 2>&1; then
  NFS_TEMP="/tmp/NerdFontsSymbolsOnly.zip"
  curl -fLo "$NFS_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/NerdFontsSymbolsOnly.zip
  unzip -o "$NFS_TEMP" -d ~/.local/share/fonts
  rm "$NFS_TEMP"
fi

fc-cache -fv

echo "==== Configuring fontconfig for Nerd Font icons ===="
mkdir -p ~/.config/fontconfig
cat >~/.config/fontconfig/fonts.conf <<'FONTCONF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <!-- Prepend Nerd Font symbols to all font fallback chains -->
  <match target="pattern">
    <edit name="family" mode="prepend">
      <string>Symbols Nerd Font</string>
    </edit>
  </match>

  <!-- Reject CJK fonts for Private Use Area codepoints used by Nerd Fonts -->
  <selectfont>
    <rejectfont>
      <glob>*CJK*</glob>
    </rejectfont>
  </selectfont>
</fontconfig>
FONTCONF

echo "==== Installing tree-sitter-cli (via Rust) ===="
if ! command -v cargo >/dev/null 2>&1; then
  echo "Installing Rust (rustup)"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
fi
if ! grep -q '\.cargo/env' "$HOME/.zshrc"; then
  echo '. "$HOME/.cargo/env"' >>"$HOME/.zshrc"
fi
cargo install tree-sitter-cli || true

###########################################################
# ZSH + Oh My Zsh
###########################################################
echo "==== Installing Zsh ===="
sudo pacman -S --noconfirm --needed zsh

ZSH_PATH=$(which zsh)
if [ "$SHELL" != "$ZSH_PATH" ]; then
  echo "Setting Zsh as default shell"
  chsh -s "$ZSH_PATH"
fi

echo "==== Installing Oh My Zsh ===="
if [ ! -d "$HOME/.oh-my-zsh" ]; then
  RUNZSH=no KEEP_ZSHRC=yes \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
fi

# Source oh-my-zsh with the robbyrussell theme (cwd + git branch + dirty marker).
# KEEP_ZSHRC=yes above means the OMZ installer didn't touch ~/.zshrc, so wire it up here.
if ! grep -q 'oh-my-zsh.sh' ~/.zshrc; then
  cat >>~/.zshrc <<'OMZ'

export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME="robbyrussell"
source "$ZSH/oh-my-zsh.sh"
OMZ
fi

if ! grep -q "EDITOR" ~/.zshrc; then
  echo "export EDITOR='nvim'" >>~/.zshrc
  echo "export VISUAL='nvim'" >>~/.zshrc
fi

###########################################################
# tmux + tmuxinator
###########################################################
echo "==== Installing tmux ===="
sudo pacman -S --noconfirm --needed tmux ruby ruby-erb

gem install --user-install tmuxinator

# tmuxinator installs into the user gem bindir (e.g. ~/.local/share/gem/ruby/3.4.0/bin),
# which isn't on PATH by default. Add it, and define the conventional `mux` alias.
if ! grep -q 'Gem.user_dir' ~/.zshrc; then
  cat >>~/.zshrc <<'GEMPATH'

if command -v ruby >/dev/null 2>&1; then
  export PATH="$(ruby -e 'puts Gem.user_dir')/bin:$PATH"
fi
GEMPATH
fi
if ! grep -q "alias mux=" ~/.zshrc; then
  echo "alias mux='tmuxinator'" >>~/.zshrc
fi

# tmux plugin repos (tpm, tmux-yank) are cloned in clone-repos.sh.

###########################################################
# Chrome
###########################################################
echo "==== Installing Google Chrome ===="
yay -S --noconfirm --needed google-chrome

if ! grep -q "alias chrome=" ~/.zshrc; then
  echo "alias chrome='nohup google-chrome --disable-gpu-compositing > /dev/null 2>&1 & disown'" >>~/.zshrc
fi

###########################################################
# Docker
###########################################################
echo "==== Installing Docker ===="
sudo pacman -S --noconfirm --needed docker docker-buildx docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

###########################################################
# earlyoom (userspace OOM killer)
#
# Safety net for swap-thrash freezes: host Roslyn LSP loading a full solution
# on top of a running devcontainer can exhaust RAM. With no OOM daemon the
# kernel thrashes swap indefinitely and only a hard reboot recovers. earlyoom
# SIGTERMs the biggest hog first. Thresholds + avoid/prefer lists live in
# etc/default/earlyoom (installed by apply-etc.sh); pairs with vm.swappiness=10
# (etc/sysctl.d/99-memory.conf, also applied by apply-etc.sh).
###########################################################
echo "==== Installing earlyoom ===="
sudo pacman -S --noconfirm --needed earlyoom
sudo systemctl enable --now earlyoom
# Re-run safe: pick up any edits to /etc/default/earlyoom (enable --now is a
# no-op on an already-running unit and would not reload changed args).
sudo systemctl restart earlyoom

###########################################################
# Lazydocker
###########################################################
echo "==== Installing Lazydocker ===="
if ! command -v lazydocker >/dev/null 2>&1; then
  LAZYDOCKER_VERSION=$(curl -s https://api.github.com/repos/jesseduffield/lazydocker/releases/latest | grep tag_name | cut -d '"' -f4)
  curl -L "https://github.com/jesseduffield/lazydocker/releases/download/${LAZYDOCKER_VERSION}/lazydocker_${LAZYDOCKER_VERSION#v}_Linux_x86_64.tar.gz" -o lazydocker.tar.gz
  sudo tar -xzvf lazydocker.tar.gz -C /usr/local/bin lazydocker
  rm lazydocker.tar.gz
fi

if ! grep -q "alias lzd=" ~/.zshrc; then
  echo "alias lzd='lazydocker'" >>~/.zshrc
fi

###########################################################
# kubectl
###########################################################
echo "==== Installing kubectl ===="
sudo pacman -S --noconfirm --needed kubectl

###########################################################
# helm
###########################################################
echo "==== Installing helm ===="
sudo pacman -S --noconfirm --needed helm

###########################################################
# k9s
###########################################################
echo "==== Installing k9s ===="
sudo pacman -S --noconfirm --needed k9s

###########################################################
# Flux CLI
###########################################################
echo "==== Installing Flux CLI ===="
if ! command -v flux >/dev/null 2>&1; then
  curl -s https://fluxcd.io/install.sh | sudo bash
fi

echo "==== Installing Flux k9s Plugin ===="
mkdir -p ~/.config/k9s/plugins/
curl https://raw.githubusercontent.com/derailed/k9s/refs/heads/master/plugins/flux.yaml -o ~/.config/k9s/plugins/flux.yaml

###########################################################
# Bottom (btm)
###########################################################
echo "==== Installing Bottom (btm) ===="
sudo pacman -S --noconfirm --needed bottom

###########################################################
# Email + Calendar: Evolution + evolution-ews
#
# Native EWS client for on-prem Exchange (pre-IMAP). Stores
# credentials via libsecret/GNOME keyring, not plaintext.
# Add account via Edit > Accounts; type = Exchange Web Services.
#
# gnome-keyring = Secret Service daemon (no GNOME DE required).
# seahorse = GUI to inspect/rename keyrings.
# PAM auto-unlock wired via etc/pam.d/login (applied by
# apply-etc.sh). First Evolution launch: set keyring password
# equal to login password so it unlocks silently every login.
###########################################################
echo "==== Installing Evolution + evolution-ews ===="
sudo pacman -S --noconfirm --needed evolution evolution-ews gnome-keyring seahorse libsecret

###########################################################
# LazyGit
###########################################################
echo "==== Installing LazyGit ===="
sudo pacman -S --noconfirm --needed lazygit

if ! grep -q "alias lzg=" ~/.zshrc; then
  echo "alias lzg='lazygit'" >>~/.zshrc
fi

###########################################################
# Tig
###########################################################
sudo pacman -S --noconfirm --needed tig

###########################################################
# yazi (terminal file manager)
###########################################################
echo "==== Installing yazi ===="
# yazi core + previewer deps:
#   resvg: SVG (yazi's svg previewer calls the `resvg` CLI, not rsvg-convert).
#   ttf-jetbrains-mono-nerd: satisfies yazi's nerd-fonts group dep non-interactively
#     (matches the foot font choice).
#   jq/p7zip/zoxide: yazi optdeps for json/archive previewers + cd-history.
#   chafa: sixel image rendering in foot.
#   ffmpegthumbnailer/imagemagick/poppler/mediainfo/bat: thumbnailers + viewers
#     yazi uses for video/raster/PDF/media-info/syntax-highlighted text.
#   atool: archive listing fallback.
sudo pacman -S --noconfirm --needed \
  yazi \
  resvg \
  ttf-jetbrains-mono-nerd \
  jq \
  p7zip \
  zoxide \
  chafa \
  ffmpegthumbnailer \
  poppler \
  imagemagick \
  mediainfo \
  bat \
  atool

# cd-on-quit wrapper from yazi docs:
# https://yazi-rs.github.io/docs/quick-start#shell-wrapper
if ! grep -q "yazi-cwd" ~/.zshrc; then
  cat >>~/.zshrc <<'EOF'

# yazi cd-on-quit
function y() {
  local tmp="$(mktemp -t "yazi-cwd.XXXXXX")" cwd
  yazi "$@" --cwd-file="$tmp"
  if cwd="$(command cat -- "$tmp")" && [ -n "$cwd" ] && [ "$cwd" != "$PWD" ]; then
    builtin cd -- "$cwd"
  fi
  rm -f -- "$tmp"
}
EOF
fi

###########################################################
# Beekeeper Studio
###########################################################
echo "==== Installing Beekeeper Studio ===="
yay -S --noconfirm --needed beekeeper-studio-bin

###########################################################
# Remmina
###########################################################
echo "==== Installing Remmina ===="
sudo pacman -S --noconfirm --needed remmina freerdp libvncserver

###########################################################
# LibreOffice
###########################################################
echo "==== Installing LibreOffice ===="
sudo pacman -S --noconfirm --needed libreoffice-fresh

###########################################################
# Azure CLI
###########################################################
echo "==== Installing Azure CLI ===="
yay -S --noconfirm --needed azure-cli

###########################################################
# GitHub Copilot CLI
###########################################################
echo "==== Installing GitHub Copilot CLI ===="
sudo npm install -g @github/copilot

###########################################################
# Gonzo (log viewer) -- gonzofk fork
###########################################################
echo "==== Installing gonzofk ===="
mkdir -p ~/.local/bin
gh release download --repo alex-irvine/gonzo \
  --pattern 'gonzofk-linux-amd64' \
  --output ~/.local/bin/gonzofk \
  --clobber
chmod +x ~/.local/bin/gonzofk

###########################################################
# logcli (Grafana Loki CLI)
###########################################################
echo "==== Installing logcli ===="
if ! command -v logcli >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/logcli" ]; then
  LOGCLI_VERSION=$(curl -s https://api.github.com/repos/grafana/loki/releases/latest | grep '"tag_name"' | cut -d '"' -f4)
  mkdir -p ~/.local/bin
  curl -L "https://github.com/grafana/loki/releases/download/${LOGCLI_VERSION}/logcli-linux-amd64.zip" -o /tmp/logcli-linux-amd64.zip
  unzip -o /tmp/logcli-linux-amd64.zip -d /tmp
  chmod +x /tmp/logcli-linux-amd64
  mv /tmp/logcli-linux-amd64 ~/.local/bin/logcli
  rm /tmp/logcli-linux-amd64.zip
fi

if ! grep -q "logcli completion zsh" ~/.zshrc; then
  echo "" >>~/.zshrc
  echo "# logcli autocompletion" >>~/.zshrc
  echo 'eval "$(logcli --completion-script-zsh)"' >>~/.zshrc
fi

echo "==== Configuring Gonzo for Serilog ===="
mkdir -p ~/.config/gonzo/formats
cat >~/.config/gonzo/formats/serilog.yaml <<'EOF'
name: serilog
description: Serilog compact JSON format (RenderedCompactJsonFormatter)
type: json

mapping:
  timestamp:
    field: "@t"
    time_format: "2006-01-02T15:04:05.9999999Z07:00"

  severity:
    field: "@l"
    default: "INFO"

  body:
    field: "@m"

  exception:
    field: "@x"

  auto_map_remaining: true
EOF

cat >~/.config/gonzo/formats/serilog-console.yaml <<'EOF'
name: serilog-console
description: Serilog console output with JSON properties
type: text

pattern:
  use_regex: true
  main: '^\s*\[(?P<timestamp>\d{2}:\d{2}:\d{2})\s+(?P<level>\w+)\]\s+(?P<message>.*?)(?:\s+(\{.*\}))?$'

mapping:
  timestamp:
    field: timestamp
    time_format: "15:04:05"

  severity:
    field: level
    transform: uppercase
    default: "INFO"

  body:
    field: message
EOF

###########################################################
# yq (YAML processor)
###########################################################
echo "==== Installing yq ===="
sudo pacman -S --noconfirm --needed go-yq

###########################################################
# air (Go live-reloader)
###########################################################
echo "==== Installing air ===="
go install github.com/air-verse/air@latest

###########################################################
# datascopesystems private releases
# (gh auth + read:packages scope handled at top of script)
###########################################################
echo "==== Installing lazyorc ===="
mkdir -p ~/.local/bin
gh release download --repo datascopesystems/lazyorc \
  --pattern 'lazyorc-linux-amd64' \
  --output ~/.local/bin/lazyorc \
  --clobber
chmod +x ~/.local/bin/lazyorc

echo "==== Installing lazyfleet ===="
gh release download --repo datascopesystems/lazyfleet \
  --pattern 'lazyfleet-linux-amd64' \
  --output ~/.local/bin/lazyfleet \
  --clobber
chmod +x ~/.local/bin/lazyfleet

# Ensure ~/.local/bin is on PATH
if ! grep -q 'local/bin' ~/.zshrc; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >>~/.zshrc
fi

if ! grep -q "alias lzo=" ~/.zshrc; then
  echo "alias lzo='lazyorc'" >>~/.zshrc
fi
if ! grep -q "alias lzf=" ~/.zshrc; then
  echo "alias lzf='lazyfleet'" >>~/.zshrc
fi

if ! grep -q 'exec sway' ~/.zshrc; then
  echo 'if [ -z "$WAYLAND_DISPLAY" ] && [ "$XDG_VTNR" -eq 1 ]; then exec sway; fi' >> ~/.zshrc
fi

###########################################################
# Claude Code (CLI + hooks + plugins)
###########################################################
echo "==== Running claude-setup.sh ===="
bash "$SCRIPT_DIR/claude-setup.sh"

echo "==== Setup complete! ===="
echo ""
echo "Restart required for Docker group changes to take effect."
echo "Press prefix + I in tmux to install plugins."
