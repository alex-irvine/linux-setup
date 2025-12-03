# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Repository Purpose

This is a Pop!_OS/Ubuntu system configuration repository containing automated setup scripts for a development workstation. The scripts handle full system bootstrapping from a fresh install.

## Key Scripts

### popos-setup.sh
Main system setup script that installs and configures the complete development environment. Run once on a fresh Pop!_OS or Ubuntu system:

```bash
./popos-setup.sh
```

**What it installs:**
- Shell: Zsh + Oh My Zsh
- Development tools: VS Code (with extensions), Git, Node.js/npm, Docker + Docker Compose
- Docker utilities: Lazydocker (aliased as `lzd`)
- System monitoring: Bottom (btm)
- GUI applications: Google Chrome, GitKraken, DBeaver, Remmina
- Email client: Evolution + Evolution EWS
- GitHub tooling: Copilot CLI, GitHub CLI (gh)

**Important details:**
- Script uses `wait_for_apt()` function to handle APT lock contention
- Automatically detects Ubuntu/Pop!_OS version codename for repository configuration
- Sets Zsh as default shell (requires logout to take effect)
- Adds user to Docker group (requires logout/restart to take effect)
- Creates `lzd` alias for Lazydocker in `~/.zshrc`

### fix-suspend.sh
Configures systemd and ACPI wakeup settings to fix lid-close suspend behavior on laptops:

```bash
./fix-suspend.sh
```

**What it does:**
- Configures `/etc/systemd/logind.conf` for proper suspend on lid close
- Creates `/usr/local/bin/disable-wake.sh` to disable unwanted wakeup sources
- Installs `disable-wake.service` systemd service that runs on boot and after suspend
- Disables lid switch, USB, USB-C, battery, and power button wakeup sources
- Requires logout for logind changes to take effect

## Architecture & Design Patterns

### APT Lock Handling
Both scripts use `wait_for_apt()` to poll for APT lock release before package operations. This handles conflicts with automatic updaters or other package managers.

### Idempotency Considerations
- `popos-setup.sh` checks for existing installations (e.g., Oh My Zsh directory, VS Code repo)
- Repository/keyring configurations check for existing files before adding
- Alias additions to `.zshrc` use `grep -q` to prevent duplicates
- Not fully idempotent for .deb downloads (always downloads fresh package files)

### Version Detection
Scripts dynamically detect the latest versions from GitHub API for tools like Lazydocker and Bottom, ensuring up-to-date installations without hardcoding versions.

### System Configuration Approach
`fix-suspend.sh` uses a multi-layered approach:
1. Systemd logind configuration for policy
2. ACPI wakeup device disabling via `/proc/acpi/wakeup`
3. Device-specific sysfs wakeup disabling (lid, USB, battery)
4. Systemd service for persistence across reboots and suspend cycles

## Testing Scripts

To test script modifications without running the full installation:

```bash
# Dry-run syntax check
bash -n popos-setup.sh
bash -n fix-suspend.sh

# Test specific sections by commenting out other sections
# (Both scripts use set -e, so failures will halt execution)
```

**Verification commands after running scripts:**

```bash
# Verify installed tools
which zsh code docker lazydocker btm gh copilot

# Check Docker group membership
groups | grep docker

# Verify suspend configuration
cat /etc/systemd/logind.conf
cat /proc/acpi/wakeup
systemctl status disable-wake.service
cat /sys/bus/acpi/devices/PNP0C0D:00/power/wakeup
```

## Modification Guidelines

### Adding New Package Installations
Always use `wait_for_apt` before any `apt` command:

```bash
echo "==== Installing New Package ===="
wait_for_apt
sudo apt install -y package-name
```

### Adding New .deb Downloads
Follow the pattern of downloading, installing, and cleaning up:

```bash
curl -L -o temp.deb "URL"
wait_for_apt
sudo apt install -y ./temp.deb
rm temp.deb
```

### Adding Zsh Aliases
Check for existence before appending to avoid duplicates:

```bash
if ! grep -q "alias newalias=" ~/.zshrc; then
    echo "alias newalias='command'" >> ~/.zshrc
fi
```

### Extending Wakeup Device Handling
Add new device checks to `/usr/local/bin/disable-wake.sh` using the pattern:

```bash
if [ -e /sys/path/to/device/power/wakeup ]; then
    echo "  Disabling device wakeup"
    echo disabled > /sys/path/to/device/power/wakeup
fi
```
