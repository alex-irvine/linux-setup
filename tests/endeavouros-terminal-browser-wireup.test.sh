#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTENT="$(<"$ROOT_DIR/endeavouros-setup.sh")"
fail() { printf 'FAIL: %s\n' "$1"; exit 1; }
[[ "$CONTENT" == *'bash "$SCRIPT_DIR/terminal-browser-setup.sh"'* ]] || fail 'missing terminal-browser setup call'
[[ "$CONTENT" == *' agents '* ]] || fail 'missing agents Stow package'
[[ "$CONTENT" != *' pi '* ]] || fail 'pi Stow package remains'
[[ "$CONTENT" != *'curl -fsSL https://terminal-browser'* ]] || fail 'raw terminal-browser installer remains'
CLAUDE_CONTENT="$(<"$ROOT_DIR/claude-setup.sh")"
[[ "$CLAUDE_CONTENT" == *'remove_mcp_if_present chrome-devtools'* ]] || fail 'Claude browser cleanup missing'
[[ "$CLAUDE_CONTENT" == *'add_http_mcp_if_missing betterstack'* ]] || fail 'Claude Better Stack MCP helper missing'
[[ "$CLAUDE_CONTENT" == *'add_http_mcp_if_missing composio'* ]] || fail 'Claude Composio MCP helper missing'
[[ "$CLAUDE_CONTENT" != *'claude mcp add --transport http -s user betterstack'* ]] || fail 'Claude Better Stack MCP is unconditionally added'
[[ "$CLAUDE_CONTENT" != *'claude mcp add --transport http -s user composio'* ]] || fail 'Claude Composio MCP is unconditionally added'
clone=$(grep -n 'bash "$SCRIPT_DIR/clone-repos.sh"' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
mapfile -t setup_lines < <(grep -n 'bash "$SCRIPT_DIR/terminal-browser-setup.sh"' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
setup="${setup_lines[0]}"
cleanup=$(grep -n '^for d in ~/.config/sway' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
initial_stow=$(grep -n '^stow --target="$HOME" --restow agents evolution' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
claude=$(grep -n 'bash "$SCRIPT_DIR/claude-setup.sh"' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
opencode=$(grep -n 'bash "$SCRIPT_DIR/opencode-setup.sh"' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
hermes=$(grep -n 'bash "$SCRIPT_DIR/hermes-setup.sh"' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
hermes_restow=$(grep -n 'stow --no-folding --target="$HOME" --restow hermes' "$ROOT_DIR/endeavouros-setup.sh" | tail -1 | cut -d: -f1)
verify=$(grep -n -- '--verify-only' "$ROOT_DIR/endeavouros-setup.sh" | cut -d: -f1)
[[ "${#setup_lines[@]}" -eq 2 ]] || fail 'expected normal and final terminal-browser setup calls'
[[ -n "$verify" && "$clone" -lt "$cleanup" && "$cleanup" -lt "$initial_stow" && "$initial_stow" -lt "$setup" && "$setup" -lt "$claude" && "$claude" -lt "$opencode" && "$opencode" -lt "$hermes" && "$hermes" -lt "$hermes_restow" && "$hermes_restow" -lt "$verify" ]] || fail 'clone/cleanup/initial-stow/setup/provider/final-verification ordering'
for marker in 'bash "$SCRIPT_DIR/claude-setup.sh"' 'bash "$SCRIPT_DIR/opencode-setup.sh"' 'bash "$SCRIPT_DIR/hermes-setup.sh"' 'stow --no-folding --target="$HOME" --restow hermes'; do
  line=$(grep -nF "$marker" "$ROOT_DIR/endeavouros-setup.sh" | tail -1 | cut -d: -f1)
  [[ "$line" -lt "$verify" ]] || fail "provider readiness before final verify: $marker"
done
if command -v stow >/dev/null 2>&1; then
  stow_tmp="$(mktemp -d "${TMPDIR:-/tmp}/terminal-browser-stow.XXXXXX")"
  trap 'rm -rf -- "$stow_tmp"' EXIT
  mkdir -p "$stow_tmp/home" "$stow_tmp/dotfiles/zsh"
  printf 'managed\n' >"$stow_tmp/dotfiles/zsh/.zshrc"
  printf 'unmanaged\n' >"$stow_tmp/home/.zshrc"
  cp "$stow_tmp/home/.zshrc" "$stow_tmp/unmanaged-zshrc.before"
  set +e
  stow_output="$(stow --dir="$stow_tmp/dotfiles" --target="$stow_tmp/home" --restow zsh 2>&1)"
  stow_status=$?
  set -e
  [[ "$stow_status" -ne 0 ]] || fail 'GNU Stow unexpectedly replaced unmanaged .zshrc'
  [[ "$stow_output" == *'cannot stow'* ]] || fail 'GNU Stow conflict evidence missing'
  cmp -s "$stow_tmp/home/.zshrc" "$stow_tmp/unmanaged-zshrc.before" || fail 'GNU Stow changed unmanaged .zshrc after conflict'
  [[ -f "$stow_tmp/home/.zshrc" && ! -L "$stow_tmp/home/.zshrc" ]] || fail 'conflicting .zshrc is no longer the original regular file'
  printf '%s\n' 'PASS: GNU Stow conflict preserved standalone unmanaged zsh byte-for-byte'
  rm -f "$stow_tmp/home/.zshrc"
  stow --dir="$stow_tmp/dotfiles" --target="$stow_tmp/home" --restow zsh
  [[ -L "$stow_tmp/home/.zshrc" ]] || fail 'GNU Stow did not install managed .zshrc symlink'
  [[ "$(readlink -e "$stow_tmp/home/.zshrc")" == "$stow_tmp/dotfiles/zsh/.zshrc" ]] || fail 'GNU Stow installed wrong .zshrc target'
  stow --dir="$stow_tmp/dotfiles" --target="$stow_tmp/home" --restow zsh
else
  printf '%s\n' 'SKIP: GNU Stow unavailable; isolated conflict demonstration skipped'
fi
printf 'PASS: endeavouros terminal-browser wireup present\n'
