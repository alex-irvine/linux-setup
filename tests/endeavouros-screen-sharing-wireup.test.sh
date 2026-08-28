#!/usr/bin/env bash
set -euo pipefail

FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/endeavouros-setup.sh"
BASE_PACKAGES="$(awk '
  /echo "==== Installing base tools ===="/ { capture=1 }
  capture { print }
  capture && /^#{10,}$/ { exit }
' "$FILE")"

for package in xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-wlr; do
  [[ "$BASE_PACKAGES" == *"$package"* ]] || {
    echo "FAIL: missing $package base package install"
    exit 1
  }
done

echo "PASS: EndeavourOS screen-sharing packages present"
