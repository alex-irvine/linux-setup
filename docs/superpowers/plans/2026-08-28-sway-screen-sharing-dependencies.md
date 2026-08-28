# Sway Screen-Sharing Dependencies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the Wayland portal packages required for browser screen sharing in fresh EndeavourOS/Sway installations.

**Architecture:** Keep all three portal packages in the existing base `pacman --needed` transaction beside Sway and PipeWire. Add one static shell test, matching the repository's existing EndeavourOS wire-up tests, to prevent the required packages from disappearing from the bootstrap script.

**Tech Stack:** Bash, pacman, shell assertion tests

## Global Constraints

- Keep repeated setup runs idempotent through the existing `pacman --needed` invocation.
- Do not add portal configuration files, browser flags, runtime service restarts, or a new setup section.
- Preserve `xdg-desktop-portal-gtk` for general desktop portals and add `xdg-desktop-portal-wlr` for Sway ScreenCast support.

---

### Task 1: Persist Sway screen-sharing packages

**Files:**
- Modify: `endeavouros-setup.sh:14-20`
- Create: `tests/endeavouros-screen-sharing-wireup.test.sh`

**Interfaces:**
- Consumes: the existing base `sudo pacman -S --noconfirm --needed` package transaction
- Produces: a bootstrap package list containing `xdg-desktop-portal`, `xdg-desktop-portal-gtk`, and `xdg-desktop-portal-wlr`

- [x] **Step 1: Write the failing package wire-up test**

Create `tests/endeavouros-screen-sharing-wireup.test.sh`:

```bash
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
```

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
bash tests/endeavouros-screen-sharing-wireup.test.sh
```

Expected: exit 1 with `FAIL: missing xdg-desktop-portal base package install`.

- [x] **Step 3: Add the portal packages to the base package transaction**

Change the Sway/PipeWire portion of `endeavouros-setup.sh` to:

```bash
  sway waybar wofi foot mako swaylock swayidle xorg-xwayland \
  wl-clipboard pipewire pipewire-pulse wireplumber pulsemixer \
  xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-wlr \
```

- [x] **Step 4: Run the focused test to verify it passes**

Run:

```bash
bash tests/endeavouros-screen-sharing-wireup.test.sh
```

Expected: exit 0 with `PASS: EndeavourOS screen-sharing packages present`.

- [x] **Step 5: Run all EndeavourOS wire-up tests**

Run:

```bash
for test_file in tests/endeavouros-*.test.sh; do bash "$test_file"; done
```

Expected: every test prints `PASS:` and the loop exits 0.

- [x] **Step 6: Validate shell syntax and whitespace**

Run:

```bash
bash -n endeavouros-setup.sh tests/endeavouros-screen-sharing-wireup.test.sh
git diff --check
```

Expected: both commands exit 0 with no output.
