# Tailscale Remote tmux

## What this gives you
- Private tailnet path to SSH into this host from mobile.
- Reuse existing local tmux sessions.

## Host setup
1. Run `bash setup-tailscale.sh`.
2. If prompted, run `sudo tailscale up --ssh`.
3. Verify with `tailscale status` and `tailscale ip -4`.

## Mobile apps (manual install)
- Install `Tailscale` app on iOS/Android.
- Install an SSH app/client:
  - iOS: Termius or Blink Shell.
  - Android: Termius or JuiceSSH.

## First connect from phone
1. Connect phone to tailnet in Tailscale app.
2. SSH to host tailnet name/IP.
3. Run `tmux ls` then attach.

## Daily usage
- SSH in, run `tmxw` (or `tmux attach -t work`).

## Troubleshooting
- If `tailscaled` not active: `sudo systemctl status tailscaled`.
- If login missing: `sudo tailscale up --ssh`.
- If connection is slow: likely relay path; test another network.

## Lost device response
1. Remove compromised phone from Tailscale admin/devices.
2. Rotate SSH keys if using OpenSSH fallback.
3. Re-authenticate trusted devices.
