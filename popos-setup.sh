#!/usr/bin/env bash
wait_for_apt() {
  while sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
    echo "APT is locked by another process, waiting..."
    sleep 2
  done
}

set -e

echo "==== Detecting Pop!_OS / Ubuntu version ===="
VERSION_CODENAME=$(grep VERSION_CODENAME /etc/os-release | cut -d= -f2)
echo "Detected codename: $VERSION_CODENAME"

echo "==== Updating system ===="
wait_for_apt
sudo apt update && sudo apt upgrade -y

echo "==== Installing required tools ===="
wait_for_apt
sudo apt install -y curl wget gnupg ca-certificates apt-transport-https software-properties-common build-essential unzip clang libclang-dev pkg-config

echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p

###########################################################
# Golang (handy terminal utilities and dev env)
###########################################################
echo "==== Installing golang ===="
sudo add-apt-repository ppa:longsleep/golang-backports
sudo apt update
sudo apt install golang-go

###########################################################
# Node.js + npm
# Required by Mason (nvim) for LSP servers
###########################################################
echo "==== Installing Node.js + npm ===="
wait_for_apt
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

###########################################################
# Neovim
# Install from official release tarball
# ###########################################################
echo "==== Installing Neovim ===="

# Remove apt Neovim to avoid version conflicts
wait_for_apt
sudo apt remove -y neovim || true

# Download & install latest release build
TMP_DIR="/tmp/nvim-install"
NVIM_TARBALL_URL="https://github.com/neovim/neovim-releases/releases/latest/download/nvim-linux-x86_64.tar.gz"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
curl -L -o "$TMP_DIR/nvim-linux-x86_64.tar.gz" "$NVIM_TARBALL_URL"

sudo rm -rf /opt/nvim
sudo mkdir -p /opt/nvim
sudo tar -xzf "$TMP_DIR/nvim-linux-x86_64.tar.gz" -C /opt/nvim --strip-components=1
sudo ln -sf /opt/nvim/bin/nvim /usr/local/bin/nvim

rm -rf "$TMP_DIR"

echo "Neovim version now:"
nvim --version | head -n 2

echo "==== Installing Nerd Fonts ===="
mkdir -p ~/.local/share/fonts

# JetBrains Mono Nerd Font (optional - for terminal font)
JBM_TEMP="/tmp/JetBrainsMono.zip"
curl -fLo "$JBM_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/JetBrainsMono.zip
mkdir -p ~/.local/share/fonts/JetBrainsMono
unzip -o "$JBM_TEMP" -d ~/.local/share/fonts/JetBrainsMono
rm "$JBM_TEMP"

# Nerd Font Symbols Only (required for icon fallback)
NFS_TEMP="/tmp/NerdFontsSymbolsOnly.zip"
curl -fLo "$NFS_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/NerdFontsSymbolsOnly.zip
unzip -o "$NFS_TEMP" -d ~/.local/share/fonts
rm "$NFS_TEMP"

fc-cache -fv

# Fontconfig: prioritize Nerd Font symbols over CJK fonts
# (prevents icons from rendering as kanji characters)
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

# Clone nvim config
if [ ! -d ~/.config/nvim ]; then
  echo "📥 Cloning nvim configuration..."
  git clone https://github.com/alex-irvine/nvim-config.git ~/.config/nvim
fi

echo "✅ Neovim config installed"
echo "   Plugins, LSPs, formatters, and linters will auto-install on first launch"
echo "   Run 'nvim' to start the installation"

# tree-sitter-cli is needed to compile treesitter parsers
# Mason's binary requires newer glibc than Pop!_OS has, so build from source with Rust
# Install Rust if missing and add cargo bin to PATH now and for future shells
echo "==== Installing tree-sitter-cli (via Rust) ===="
if ! command -v cargo >/dev/null 2>&1; then
  echo "Installing Rust (rustup)"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  source "$HOME/.cargo/env"
fi
if ! grep -q '\.cargo/env' "$HOME/.zshrc"; then
  echo '. "$HOME/.cargo/env"' >>"$HOME/.zshrc"
fi
# Build tree-sitter-cli from source to avoid glibc version issues
cargo install tree-sitter-cli || true

###########################################################
# ZSH + Oh My Zsh (and make default)
###########################################################
echo "==== Installing Zsh ===="
wait_for_apt
sudo apt install -y zsh

if [ "$SHELL" != "/usr/bin/zsh" ]; then
  echo "Setting Zsh as default shell"
  chsh -s /usr/bin/zsh
fi

echo "==== Installing Oh My Zsh ===="
if [ ! -d "$HOME/.oh-my-zsh" ]; then
  RUNZSH=no KEEP_ZSHRC=yes \
    sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
fi

# Set nvim as default editor for k9s, lazygit, etc.
echo "export EDITOR='nvim'" >>~/.zshrc
echo "export VISUAL='nvim'" >>~/.zshrc

###########################################################
# Install tmux and tmuxinator and sync projects
###########################################################
sudo snap install tmux --classic
sudo apt-get install ruby-full
gem install tmuxinator

echo "📥 Cloning tmuxinator projects..."
git clone https://github.com/alex-irvine/tmuxinator.git ~/.config/tmuxinator

###########################################################
# Chrome
###########################################################
echo "==== Installing Google Chrome ===="
wait_for_apt
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
rm google-chrome-stable_current_amd64.deb

if ! grep -q "alias chrome=" ~/.zshrc; then
  echo "alias chrome='nohup google-chrome --disable-gpu-compositing > /dev/null 2>&1 & disown'" >>~/.zshrc
fi

###########################################################
# Docker
###########################################################
echo "==== Installing Docker ===="
# Remove conflicting packages
sudo apt remove $(dpkg --get-selections docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc | cut -f1)

# Add Docker's official GPG key:
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

wait_for_apt
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
# Add the user to the docker usergroup to allow daemon permission
sudo usermod -aG docker "$USER"

###########################################################
# Lazydocker + alias lzd
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
# kubectl (Kubernetes CLI)
###########################################################
echo "==== Installing kubectl ===="
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
rm kubectl

###########################################################
# helm
###########################################################
echo "==== Installing helm ===="
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4
chmod 700 get_helm.sh
./get_helm.sh
rm get_helm.sh

###########################################################
# k9s (Kubernetes CLI UI)
###########################################################
echo "==== Installing k9s ===="
K9S_VERSION=$(curl -s https://api.github.com/repos/derailed/k9s/releases/latest | grep tag_name | cut -d '"' -f4)
curl -L "https://github.com/derailed/k9s/releases/download/${K9S_VERSION}/k9s_Linux_amd64.tar.gz" -o k9s.tar.gz
sudo tar -xzvf k9s.tar.gz -C /usr/local/bin k9s
rm k9s.tar.gz

###########################################################
# Flux CLI (GitOps)
###########################################################
echo "==== Installing Flux CLI ===="
curl -s https://fluxcd.io/install.sh | sudo bash

# FLux k9s plugin
echo "==== Installing Flux k9s Plugin ===="
mkdir -p ~/.config/k9s/plugins/
curl https://raw.githubusercontent.com/derailed/k9s/refs/heads/master/plugins/flux.yaml -o ~/.config/k9s/plugins/flux.yaml

###########################################################
# Bottom (btm)
###########################################################
echo "==== Installing Bottom (btm) ===="

BTM_DEB_URL=$(curl -s https://api.github.com/repos/ClementTsang/bottom/releases/latest |
  grep browser_download_url |
  grep "amd64.deb" |
  grep -v "musl" |
  cut -d '"' -f 4)

echo "Downloading: $BTM_DEB_URL"
curl -L -o bottom.deb "$BTM_DEB_URL"

wait_for_apt
sudo apt install -y ./bottom.deb
rm bottom.deb

###########################################################
# Evolution
###########################################################
echo "==== Installing Evolution ===="
wait_for_apt
sudo apt install -y evolution evolution-ews

###########################################################
# Git
###########################################################
echo "==== Installing Git ===="
wait_for_apt
sudo apt install -y git

wait_for_apt
sudo apt install -y gh

###########################################################
# LazyGit (lzg)
###########################################################
echo "==== Installing Lazy Git ===="
LAZYGIT_VERSION=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | \grep -Po '"tag_name": *"v\K[^"]*')
curl -Lo lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz"
tar xf lazygit.tar.gz lazygit
sudo install lazygit -D -t /usr/local/bin/

if ! grep -q "alias lzg=" ~/.zshrc; then
  echo "alias lzg='lazygit'" >>~/.zshrc
fi

###########################################################
# Tig
###########################################################
sudo apt-get install tig

###########################################################
# DBeaver
###########################################################
echo "==== Installing DBeaver CE ===="
wait_for_apt
wget -q https://dbeaver.io/files/dbeaver-ce_latest_amd64.deb -O dbeaver.deb
sudo apt install -y ./dbeaver.deb
rm dbeaver.deb

###########################################################
# Remmina (RDP/VNC client)
###########################################################
echo "==== Installing Remmina ===="
wait_for_apt
sudo apt install -y remmina remmina-plugin-rdp remmina-plugin-vnc

###########################################################
# Azure CLI
###########################################################
echo "==== Installing Azure CLI ===="
wait_for_apt
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

###########################################################
# GitHub Copilot CLI
###########################################################
echo "==== Installing GitHub Copilot CLI ===="
sudo npm install -g @github/copilot

export PATH="$PATH:$(npm bin -g)"

if ! command -v copilot &>/dev/null; then
  echo "ERROR: Copilot CLI not found in PATH"
  exit 1
fi

copilot --version
echo "GitHub Copilot CLI installed successfully"

echo "==== Installing Copilot Terminal ===="
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg

echo \
  "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
https://cli.github.com/packages stable main" |
  sudo tee /etc/apt/sources.list.d/github-cli.list

echo "==== Setup complete! ===="
echo ""
echo "For suspend/lid-close configuration, run: ~/Proj/linux-setup/fix-suspend.sh"
echo "Restart required for Docker group changes to take effect."
echo "Run $(gh auth login) to login to github and git"
