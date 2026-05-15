#!/usr/bin/env bash
set -e

###########################################################
# EndeavourOS / Arch setup script
###########################################################

echo "==== Updating system ===="
sudo pacman -Syu --noconfirm

echo "==== Installing base tools ===="
sudo pacman -S --noconfirm --needed \
  base-devel curl wget gnupg ca-certificates unzip clang pkgconf git

echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p

sudo pacman -S --noconfirm --needed \
  sway waybar wofi kitty mako swaylock xorg-xwayland \
  wl-clipboard pipewire pipewire-pulse wireplumber pulsemixer \
  bluez bluez-utils network-manager-applet pulsemixer stow \
  grim slurp satty

###########################################################
# Dotfiles (single repo, stowed)
#
# Replaces the old per-tool clone blocks. Each top-level
# folder in ~/dotfiles is a stow package whose tree mirrors
# $HOME (e.g. dotfiles/sway/.config/sway/config -> ~/.config/sway/config).
###########################################################
echo "==== Cloning dotfiles repo ===="
if [ ! -d ~/dotfiles/.git ]; then
  git clone https://github.com/alex-irvine/dotfiles.git ~/dotfiles
else
  git -C ~/dotfiles pull --ff-only
fi

echo "==== Clearing default configs that conflict with stow ===="
# sway/kitty/mako/nvim auto-create config dirs on first launch; clear
# them so stow can take over. Also drop the stale per-tool config
# files at $HOME root.
rm -rf ~/.config/sway ~/.config/mako ~/.config/kitty \
       ~/.config/nvim ~/.config/tmuxinator
rm -f  ~/.zshrc ~/.tmux.conf

echo "==== Stowing dotfiles ===="
cd ~/dotfiles
stow --target="$HOME" --restow claude kitty mako nvim sway tmux tmuxinator zsh
cd -

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
yay -S bluetuith

###########################################################
# Golang
###########################################################
echo "==== Installing golang ===="
sudo pacman -S --noconfirm --needed go

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

JBM_TEMP="/tmp/JetBrainsMono.zip"
curl -fLo "$JBM_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/JetBrainsMono.zip
mkdir -p ~/.local/share/fonts/JetBrainsMono
unzip -o "$JBM_TEMP" -d ~/.local/share/fonts/JetBrainsMono
rm "$JBM_TEMP"

NFS_TEMP="/tmp/NerdFontsSymbolsOnly.zip"
curl -fLo "$NFS_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/NerdFontsSymbolsOnly.zip
unzip -o "$NFS_TEMP" -d ~/.local/share/fonts
rm "$NFS_TEMP"

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

echo "Installing tmux plugin manager (tpm)..."
if [ ! -d ~/.tmux/plugins/tpm ]; then
  git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
fi

if [ ! -d ~/.tmux/plugins/tmux-yank ]; then
  git clone https://github.com/tmux-plugins/tmux-yank ~/.tmux/plugins/tmux-yank
fi

###########################################################
# Chrome
###########################################################
echo "==== Installing Google Chrome ===="
yay -S --noconfirm google-chrome

if ! grep -q "alias chrome=" ~/.zshrc; then
  echo "alias chrome='nohup google-chrome --disable-gpu-compositing > /dev/null 2>&1 & disown'" >>~/.zshrc
fi

###########################################################
# Docker
###########################################################
echo "==== Installing Docker ===="
sudo pacman -S --noconfirm --needed docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

###########################################################
# Lazydocker
###########################################################
echo "==== Installing Lazydocker ===="
LAZYDOCKER_VERSION=$(curl -s https://api.github.com/repos/jesseduffield/lazydocker/releases/latest | grep tag_name | cut -d '"' -f4)
curl -L "https://github.com/jesseduffield/lazydocker/releases/download/${LAZYDOCKER_VERSION}/lazydocker_${LAZYDOCKER_VERSION#v}_Linux_x86_64.tar.gz" -o lazydocker.tar.gz
sudo tar -xzvf lazydocker.tar.gz -C /usr/local/bin lazydocker
rm lazydocker.tar.gz

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
curl -s https://fluxcd.io/install.sh | sudo bash

echo "==== Installing Flux k9s Plugin ===="
mkdir -p ~/.config/k9s/plugins/
curl https://raw.githubusercontent.com/derailed/k9s/refs/heads/master/plugins/flux.yaml -o ~/.config/k9s/plugins/flux.yaml

###########################################################
# Bottom (btm)
###########################################################
echo "==== Installing Bottom (btm) ===="
sudo pacman -S --noconfirm --needed bottom

###########################################################
# Evolution
###########################################################
echo "==== Installing Evolution ===="
sudo pacman -S --noconfirm --needed evolution evolution-ews

###########################################################
# Git + gh
###########################################################
echo "==== Installing Git + GitHub CLI ===="
sudo pacman -S --noconfirm --needed git github-cli

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
# DBeaver
###########################################################
echo "==== Installing DBeaver CE ===="
yay -S --noconfirm dbeaver-ce

###########################################################
# Remmina
###########################################################
echo "==== Installing Remmina ===="
sudo pacman -S --noconfirm --needed remmina freerdp libvncserver

###########################################################
# Azure CLI
###########################################################
echo "==== Installing Azure CLI ===="
yay -S --noconfirm azure-cli

###########################################################
# GitHub Copilot CLI
###########################################################
echo "==== Installing GitHub Copilot CLI ===="
sudo npm install -g @github/copilot

###########################################################
# Gonzo (log viewer)
###########################################################
echo "==== Installing Gonzo ===="
go install github.com/control-theory/gonzo/cmd/gonzo@v0.3.2

###########################################################
# logcli (Grafana Loki CLI)
###########################################################
echo "==== Installing logcli ===="
LOGCLI_VERSION=$(curl -s https://api.github.com/repos/grafana/loki/releases/latest | grep '"tag_name"' | cut -d '"' -f4)
mkdir -p ~/.local/bin
curl -L "https://github.com/grafana/loki/releases/download/${LOGCLI_VERSION}/logcli-linux-amd64.zip" -o /tmp/logcli-linux-amd64.zip
unzip -o /tmp/logcli-linux-amd64.zip -d /tmp
chmod +x /tmp/logcli-linux-amd64
mv /tmp/logcli-linux-amd64 ~/.local/bin/logcli
rm /tmp/logcli-linux-amd64.zip

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
# GitHub auth + datascopesystems tools
# lazyorc and lazyfleet are private releases — must auth first
###########################################################
echo "==== GitHub CLI Authentication ===="
echo "Authenticate now — required for lazyorc and lazyfleet install."
gh auth login
gh auth refresh -s read:packages

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

echo 'if [ -z "$WAYLAND_DISPLAY" ] && [ "$XDG_VTNR" -eq 1 ]; then exec sway; fi' >> ~/.zshrc

echo "==== Setup complete! ===="
echo ""
echo "Restart required for Docker group changes to take effect."
echo "Press prefix + I in tmux to install plugins."
