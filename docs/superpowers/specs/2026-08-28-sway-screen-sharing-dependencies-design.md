# Sway Screen-Sharing Dependencies

## Goal

Ensure a fresh EndeavourOS setup can share screens from browser applications such as Slack while running Sway on Wayland.

## Design

Add `xdg-desktop-portal`, `xdg-desktop-portal-gtk`, and `xdg-desktop-portal-wlr` to the base package installation in `endeavouros-setup.sh`, beside the existing Sway and PipeWire packages. The wlroots backend provides the ScreenCast portal required by Sway; the GTK backend continues to provide the other desktop portals.

No service-management step is needed during bootstrap. The portal services are D-Bus activated and will be available when the graphical user session starts. The existing `pacman --needed` invocation keeps repeated setup runs idempotent.

## Verification

Add a focused shell test that inspects `endeavouros-setup.sh` and fails unless all three portal packages remain in the base package installation. Run that test and the existing EndeavourOS setup-script tests after the change.

## Scope

This change does not add portal configuration files, browser flags, or runtime restart logic. The current Sway session already exports `XDG_CURRENT_DESKTOP=sway`, which allows `xdg-desktop-portal` to select the wlroots backend.
