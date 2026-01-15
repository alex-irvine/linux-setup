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
sudo apt install -y curl wget gnupg ca-certificates apt-transport-https software-properties-common

echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p
echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf && sudo sysctl -p

###########################################################
# 1. Neovim + LazyVim
###########################################################
echo "==== Installing Neovim ===="
wait_for_apt
sudo apt install -y neovim

echo "==== Installing Nerd Font (JetBrains Mono) ===="
JBM_TEMP="/tmp/JetBrainsMono.zip"
curl -fLo "$JBM_TEMP" https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip
mkdir -p ~/.local/share/fonts/JetBrainsMono
unzip -o "$JBM_TEMP" -d ~/.local/share/fonts/JetBrainsMono
rm "$JBM_TEMP"
fc-cache -fv

echo "==== Installing LazyVim ===="
if [ -d "$HOME/.config/nvim" ]; then
  echo "Backing up existing nvim config..."
  mv ~/.config/nvim ~/.config/nvim.backup-$(date +%Y%m%d-%H%M%S)
fi
if [ -d "$HOME/.local/share/nvim" ]; then
  mv ~/.local/share/nvim ~/.local/share/nvim.backup-$(date +%Y%m%d-%H%M%S)
fi
if [ -d "$HOME/.local/state/nvim" ]; then
  mv ~/.local/state/nvim ~/.local/state/nvim.backup-$(date +%Y%m%d-%H%M%S)
fi
if [ -d "$HOME/.cache/nvim" ]; then
  mv ~/.cache/nvim ~/.cache/nvim.backup-$(date +%Y%m%d-%H%M%S)
fi

git clone https://github.com/LazyVim/starter ~/.config/nvim
rm -rf ~/.config/nvim/.git

echo ""
echo "IMPORTANT: Set your terminal font to 'JetBrainsMono Nerd Font' in terminal preferences."

###########################################################
# 2. ZSH + Oh My Zsh (and make default)
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

###########################################################
# 3. Chrome
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
# 4. VS Code
###########################################################
echo "==== Installing VS Code ===="

if [[ ! -f /etc/apt/sources.list.d/vscode.sources ]]; then
  echo "Adding Microsoft GPG key and repo..."

  wget -qO- https://packages.microsoft.com/keys/microsoft.asc |
    gpg --dearmor |
    sudo tee /usr/share/keyrings/microsoft.gpg >/dev/null

  cat <<EOF | sudo tee /etc/apt/sources.list.d/vscode.sources >/dev/null
Types: deb
URIs: https://packages.microsoft.com/repos/code
Suites: stable
Components: main
Architectures: amd64
Signed-By: /usr/share/keyrings/microsoft.gpg
EOF

else
  echo "VS Code repo already exists, skipping repo creation."
fi

wait_for_apt
sudo apt update
sudo apt install -y code

echo "==== Installing VS Code Extensions ===="

EXTENSIONS=(
  ms-vscode-remote.remote-containers
  vscode-icons-team.vscode-icons
  ms-vscode.resharper9-keybindings
)

for ext in "${EXTENSIONS[@]}"; do
  echo "Installing $ext ..."
  sudo -u "$SUDO_USER" code --install-extension "$ext"
done

echo "VS Code extension install complete."

###########################################################
# 5. Docker
###########################################################
echo "==== Installing Docker ===="
sudo apt remove -y docker docker.io containerd runc || true

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" |
  sudo tee /etc/apt/sources.list.d/docker.list

wait_for_apt
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER

###########################################################
# 6. Lazydocker + alias lzd
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
# 7. kubectl (Kubernetes CLI)
###########################################################
echo "==== Installing kubectl ===="
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
rm kubectl

###########################################################
# 8. k9s (Kubernetes CLI UI)
###########################################################
echo "==== Installing k9s ===="
K9S_VERSION=$(curl -s https://api.github.com/repos/derailed/k9s/releases/latest | grep tag_name | cut -d '"' -f4)
curl -L "https://github.com/derailed/k9s/releases/download/${K9S_VERSION}/k9s_Linux_amd64.tar.gz" -o k9s.tar.gz
sudo tar -xzvf k9s.tar.gz -C /usr/local/bin k9s
rm k9s.tar.gz

###########################################################
# 9. Flux CLI (GitOps)
###########################################################
echo "==== Installing Flux CLI ===="
curl -s https://fluxcd.io/install.sh | sudo bash

###########################################################
# 10. Bottom (btm)
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
# 11. Evolution
###########################################################
echo "==== Installing Evolution ===="
wait_for_apt
sudo apt install -y evolution evolution-ews

###########################################################
# 12. Git
###########################################################
echo "==== Installing Git ===="
wait_for_apt
sudo apt install -y git

###########################################################
# 13. GitKraken
###########################################################
echo "==== Installing GitKraken ===="

# Download the latest .deb directly from official site
GK_DEB_URL="https://release.gitkraken.com/linux/gitkraken-amd64.deb"

curl -L -o gitkraken.deb "$GK_DEB_URL"

# Install
wait_for_apt
sudo apt install -y ./gitkraken.deb

# Clean up
rm gitkraken.deb

###########################################################
# 14. DBeaver
###########################################################
echo "==== Installing DBeaver CE ===="
wait_for_apt
wget -q https://dbeaver.io/files/dbeaver-ce_latest_amd64.deb -O dbeaver.deb
sudo apt install -y ./dbeaver.deb
rm dbeaver.deb

###########################################################
# 15. Remmina (RDP/VNC client)
###########################################################
echo "==== Installing Remmina ===="
wait_for_apt
sudo apt install -y remmina remmina-plugin-rdp remmina-plugin-vnc

###########################################################
# 16. Azure CLI
###########################################################
echo "==== Installing Azure CLI ===="
wait_for_apt
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

###########################################################
# 17. Copilot CLI & Copilot Terminal
###########################################################
echo "==== Installing Node.js + npm (for Copilot CLI) ===="
wait_for_apt
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

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

sudo apt update
sudo apt install -y gh

echo "==== Setup complete! ===="
echo ""
echo "For suspend/lid-close configuration, run: ~/Proj/linux-setup/fix-suspend.sh"
echo "Restart required for Docker group changes to take effect."
