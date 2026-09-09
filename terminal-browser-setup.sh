#!/usr/bin/env bash
set -euo pipefail

DOTFILES="${DOTFILES:-$HOME/dotfiles}"
TERMINAL_BROWSER_INSTALLER="${TERMINAL_BROWSER_INSTALLER:-https://terminal-browser.sh/install}"
INSTALLER_TMP=""

die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
cleanup() {
  if [[ -n "$INSTALLER_TMP" && -f "$INSTALLER_TMP" ]]; then
    rm -f -- "$INSTALLER_TMP"
  fi
  return 0
}
trap cleanup EXIT

resolve_terminal_browser() {
  local candidate
  candidate="$(command -v terminal-browser 2>/dev/null || true)"
  if [[ "$candidate" == /* && -f "$candidate" && -x "$candidate" ]]; then
    printf '%s\n' "$candidate"
  elif [[ -f "$HOME/.local/bin/terminal-browser" && -x "$HOME/.local/bin/terminal-browser" ]]; then
    printf '%s\n' "$HOME/.local/bin/terminal-browser"
  else
    return 1
  fi
}

remove_mcp_if_present() {
  local server="$1" result
  if result="$(claude mcp get "$server" 2>&1)"; then
    claude mcp remove --scope user "$server"
  else
    case "$result" in
      "No MCP server named \"$server\"."*) ;;
      *) printf '%s\n' "$result" >&2; die "unable to verify Claude MCP '$server'" ;;
    esac
  fi
}

verify_mcp_absent() {
  local server result
  for server in chrome-devtools playwright; do
    if result="$(claude mcp get "$server" 2>&1)"; then
      die "forbidden Claude MCP is present: $server"
    fi
    case "$result" in
      "No MCP server named \"$server\"."*) ;;
      *) printf '%s\n' "$result" >&2; die "unable to verify Claude MCP '$server' is absent" ;;
    esac
  done
}

stow_dotfiles() {
  [[ -d "$DOTFILES" ]] || die "dotfiles directory missing: $DOTFILES"
  cd "$DOTFILES"
  stow --target="$HOME" --restow agents opencode pi zsh
  stow --no-folding --target="$HOME" --restow claude
  stow --no-folding --target="$HOME" --restow hermes
}

verify_link() {
  local path="$1" expected="$2" actual
  [[ -L "$path" ]] || die "expected symlink: $path"
  actual="$(readlink -e "$path" 2>/dev/null || true)"
  [[ "$actual" == "$expected" ]] || die "wrong symlink target: $path (expected $expected, got ${actual:-unresolved})"
}

verify_deployment() {
  local terminal_browser
  terminal_browser="$(resolve_terminal_browser)" || die "terminal-browser executable missing"
  [[ -f "$HOME/.agents/skills/terminal-browser/SKILL.md" ]] || die "missing vendor skill: $HOME/.agents/skills/terminal-browser/SKILL.md"
  verify_link "$HOME/.agents/skills/terminal-browser-workflow" "$DOTFILES/agents/.agents/skills/terminal-browser-workflow"
  verify_link "$HOME/.agents/skills/browser-debugger" "$DOTFILES/agents/.agents/skills/browser-debugger"
  verify_link "$HOME/.config/opencode/skills/terminal-browser-workflow" "$DOTFILES/agents/.agents/skills/terminal-browser-workflow"
  verify_link "$HOME/.config/opencode/skills/browser-debugger" "$DOTFILES/agents/.agents/skills/browser-debugger"
  verify_link "$HOME/.config/opencode/agents/browser-debugger.md" "$DOTFILES/opencode/.config/opencode/agents/browser-debugger.md"
  verify_link "$HOME/.claude/skills/terminal-browser-workflow" "$DOTFILES/agents/.agents/skills/terminal-browser-workflow"
  verify_link "$HOME/.claude/skills/browser-debugger" "$DOTFILES/agents/.agents/skills/browser-debugger"
  verify_link "$HOME/.claude/agents/browser-debugger.md" "$DOTFILES/claude/.claude/agents/browser-debugger.md"
  [[ -f "$HOME/.pi/agent/extensions/subagents.ts" ]] || die "missing Pi adapter: $HOME/.pi/agent/extensions/subagents.ts"
  cmp -s "$HOME/.pi/agent/extensions/subagents.ts" "$DOTFILES/pi/.pi/agent/extensions/subagents.ts" || die "Pi adapter differs from source: $HOME/.pi/agent/extensions/subagents.ts"
  verify_link "$HOME/.local/bin/tmux-browser" "$DOTFILES/agents/.local/bin/tmux-browser"
  verify_link "$HOME/.local/bin/tmux-browser-cleanup" "$DOTFILES/agents/.local/bin/tmux-browser-cleanup"
  verify_link "$HOME/.local/bin/plannotator-terminal-browser" "$DOTFILES/agents/.local/bin/plannotator-terminal-browser"
  verify_link "$HOME/.hermes/SOUL.md" "$DOTFILES/hermes/.hermes/SOUL.md"
  verify_link "$HOME/.hermes/skills/software-development/terminal-browser-workflow" "$DOTFILES/agents/.agents/skills/terminal-browser-workflow"
  verify_link "$HOME/.hermes/skills/software-development/browser-debugger" "$DOTFILES/agents/.agents/skills/browser-debugger"
  [[ -f "$terminal_browser" && -x "$terminal_browser" ]] || die "terminal-browser is not an executable regular file: $terminal_browser"
  [[ -f "$HOME/.local/bin/tmux-browser" && -x "$HOME/.local/bin/tmux-browser" ]] || die "tmux-browser is not an executable regular file: $HOME/.local/bin/tmux-browser"
  [[ -f "$HOME/.local/bin/tmux-browser-cleanup" && -x "$HOME/.local/bin/tmux-browser-cleanup" ]] || die "tmux-browser-cleanup is not an executable regular file: $HOME/.local/bin/tmux-browser-cleanup"
  [[ -f "$HOME/.local/bin/plannotator-terminal-browser" && -x "$HOME/.local/bin/plannotator-terminal-browser" ]] || die "plannotator-terminal-browser is not an executable regular file: $HOME/.local/bin/plannotator-terminal-browser"
  [[ -f "$DOTFILES/opencode/.config/opencode/opencode.jsonc" ]] || die "OpenCode source config missing"
  verify_link "$HOME/.config/opencode/opencode.jsonc" "$DOTFILES/opencode/.config/opencode/opencode.jsonc"
  if grep -Eiq '^[[:space:]]*"(chrome-devtools|playwright)"[[:space:]]*:' "$DOTFILES/opencode/.config/opencode/opencode.jsonc"; then
    die "forbidden browser MCP found in OpenCode source config"
  elif [[ $? -gt 1 ]]; then
    die "unable to inspect OpenCode source config"
  fi
}

verify_runtime() {
  local merged_config
  command -v claude >/dev/null 2>&1 || die "Claude executable required for final verification"
  command -v opencode >/dev/null 2>&1 || die "OpenCode executable required for final verification"
  verify_mcp_absent
  if ! merged_config="$(opencode debug config 2>&1)"; then
    printf '%s\n' "$merged_config" >&2
    die "opencode debug config failed during final verification"
  fi
  if ! printf '%s' "$merged_config" | node -e '
    let input = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => input += chunk);
    process.stdin.on("end", () => {
      try {
        const config = JSON.parse(input);
        const mcp = config && config.mcp;
        if (!mcp || typeof mcp !== "object" || Array.isArray(mcp)) {
          throw new Error("merged config mcp must be an object");
        }
        for (const name of ["chrome-devtools", "playwright"]) {
          if (Object.prototype.hasOwnProperty.call(mcp, name)) {
            throw new Error(`forbidden browser MCP exposed: ${name}`);
          }
        }
      } catch (error) {
        console.error(`OpenCode merged config validation error: ${error.message}`);
        process.exitCode = 1;
      }
    });
  '; then
    die "OpenCode merged runtime config failed validation"
  fi
  printf 'OK: terminal-browser, shared skills, and four provider adapters verified\n'
}

if [[ "${1:-}" != --verify-only ]]; then
  if terminal_browser="$(resolve_terminal_browser)"; then
    "$terminal_browser" upgrade
  elif [[ -f "$TERMINAL_BROWSER_INSTALLER" && -x "$TERMINAL_BROWSER_INSTALLER" ]]; then
    "$TERMINAL_BROWSER_INSTALLER"
  elif [[ "$TERMINAL_BROWSER_INSTALLER" =~ ^https://[^/[:space:]]+(/[^[:space:]]*)?$ ]]; then
    INSTALLER_TMP="$(mktemp)"
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 -o "$INSTALLER_TMP" "$TERMINAL_BROWSER_INSTALLER"
    bash "$INSTALLER_TMP"
  else
    die "TERMINAL_BROWSER_INSTALLER must be an executable regular file or an https:// URL"
  fi
  terminal_browser="$(resolve_terminal_browser)" || die "terminal-browser executable unavailable after installation"
  "$terminal_browser" setup
  if command -v claude >/dev/null 2>&1; then
    remove_mcp_if_present chrome-devtools
    remove_mcp_if_present playwright
  else
    printf 'INFO: Claude unavailable; deferring browser MCP cleanup to claude-setup.sh\n'
  fi
  stow_dotfiles
fi

verify_deployment
if [[ "${1:-}" == --verify-only ]]; then
  verify_runtime
else
  printf 'OK: terminal-browser deployment artifacts verified\n'
fi
