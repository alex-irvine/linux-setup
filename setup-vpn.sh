#!/usr/bin/env bash
set -e
# OpenVPN via NetworkManager. Profile is confidential (inline key) — never committed.
# Fetch from https://86.28.72.134/ , place at ~/.config/vpn/profile-userlocked.ovpn

CONN="profile-userlocked"
F="$HOME/.config/vpn/profile-userlocked.ovpn"

sudo pacman -S --noconfirm --needed networkmanager-openvpn
nmcli -g NAME connection show | grep -qx "$CONN" && { echo "$CONN already imported"; exit 0; }
[ -f "$F" ] || { echo "Drop profile at $F (fetch: https://86.28.72.134/), then re-run"; exit 0; }

chmod 700 "$(dirname "$F")"; chmod 600 "$F"
nmcli connection import type openvpn file "$F"
nmcli connection modify "$CONN" connection.autoconnect no +vpn.data "username=alex.irvine"
echo "Done. Connect: vpn-up"
