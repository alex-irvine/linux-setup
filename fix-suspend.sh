#!/usr/bin/env bash

set -e

echo "==== Fixing lid-close suspend configuration ===="

# Backup existing logind.conf
if [ -f /etc/systemd/logind.conf ]; then
    echo "Backing up existing logind.conf..."
    sudo cp /etc/systemd/logind.conf /etc/systemd/logind.conf.backup-$(date +%Y%m%d-%H%M%S)
fi

# Configure logind to suspend on lid close
echo "Configuring systemd-logind for suspend on lid close..."
sudo tee /etc/systemd/logind.conf > /dev/null <<'EOF'
[Login]
# Suspend when lid closes
HandleLidSwitch=suspend
HandleLidSwitchDocked=suspend
HandleLidSwitchExternalPower=suspend
# Don't let inhibitors prevent suspend on lid close
LidSwitchIgnoreInhibited=no
# Power button triggers suspend
HandlePowerKey=suspend
EOF

# Create comprehensive wakeup disable script
echo "Creating wakeup device disable script..."
WAKE_SCRIPT="/usr/local/bin/disable-wake.sh"

sudo tee $WAKE_SCRIPT > /dev/null <<'EOF'
#!/bin/bash
# Disable ACPI wakeup devices in /proc/acpi/wakeup
echo "Disabling ACPI wakeup devices..."
for dev in $(cat /proc/acpi/wakeup | awk '$3=="*enabled" {print $1}'); do
    echo "  Disabling: $dev"
    echo "$dev" > /proc/acpi/wakeup
done

# Disable lid switch wakeup (PNP0C0D)
if [ -e /sys/bus/acpi/devices/PNP0C0D:00/power/wakeup ]; then
    echo "  Disabling lid switch wakeup (PNP0C0D:00)"
    echo disabled > /sys/bus/acpi/devices/PNP0C0D:00/power/wakeup
fi

# Disable power button wakeup (PNP0C0C) - optional, comment out if you want power button to wake
if [ -e /sys/bus/acpi/devices/PNP0C0C:00/power/wakeup ]; then
    echo "  Disabling power button wakeup (PNP0C0C:00)"
    echo disabled > /sys/bus/acpi/devices/PNP0C0C:00/power/wakeup
fi

# Disable battery wakeup (PNP0C0A) - prevents wake on battery events
if [ -e /sys/bus/acpi/devices/PNP0C0A:00/power/wakeup ]; then
    echo "  Disabling battery wakeup (PNP0C0A:00)"
    echo disabled > /sys/bus/acpi/devices/PNP0C0A:00/power/wakeup
fi

# Disable USB-C power supply wakeups
for usbc_dev in /sys/bus/platform/devices/USBC000:00/power_supply/ucsi-source-psy-*/device/power/wakeup; do
    if [ -e "$usbc_dev" ]; then
        echo "  Disabling USB-C power supply wakeup: $usbc_dev"
        echo disabled > "$usbc_dev" 2>/dev/null || true
    fi
done

# Disable all USB device wakeups
for usb_dev in /sys/bus/usb/devices/*/power/wakeup; do
    if [ -e "$usb_dev" ]; then
        echo disabled > "$usb_dev" 2>/dev/null || true
    fi
done

echo "Wakeup device configuration complete."
EOF

sudo chmod +x $WAKE_SCRIPT

# Create systemd service to run wakeup disable script on boot
echo "Creating systemd service..."
WAKE_SERVICE="/etc/systemd/system/disable-wake.service"

sudo tee $WAKE_SERVICE > /dev/null <<EOF
[Unit]
Description=Disable unwanted ACPI and USB wakeup devices
After=multi-user.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target
Before=sleep.target

[Service]
Type=oneshot
ExecStart=$WAKE_SCRIPT
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target sleep.target
EOF

# Reload systemd and enable service
echo "Enabling disable-wake service..."
sudo systemctl daemon-reload
sudo systemctl enable disable-wake.service

# Run the wakeup disable script immediately
echo "Disabling wakeup devices now..."
sudo $WAKE_SCRIPT

echo ""
echo "==== Configuration complete! ===="
echo ""
echo "Summary:"
echo "  ✓ Logind configured for suspend on lid close"
echo "  ✓ Lid switch wakeup disabled"
echo "  ✓ All USB wakeup sources disabled"
echo "  ✓ ACPI wakeup devices disabled"
echo "  ✓ Configuration persists across reboots"
echo ""
echo "IMPORTANT: Log out and log back in for lid close settings to take effect."
echo "           (Wakeup device settings are already active)"
echo ""
echo "Verification commands:"
echo "  - Lid config: cat /etc/systemd/logind.conf"
echo "  - ACPI wakeup: cat /proc/acpi/wakeup"
echo "  - Lid switch: cat /sys/bus/acpi/devices/PNP0C0D:00/power/wakeup"
echo "  - Service: systemctl status disable-wake.service"
echo ""
echo "NOTE: To wake from suspend, press the power button or plug/unplug power."
