#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUT="$ROOT_DIR/terminal-browser-setup.sh"
FIXTURES=()
cleanup() { local fixture; for fixture in "${FIXTURES[@]}"; do rm -rf -- "$fixture"; done; }
trap cleanup EXIT HUP INT TERM

new_fixture() {
  TEST_TMP="$(mktemp -d)"; FIXTURES+=("$TEST_TMP")
  mkdir -p "$TEST_TMP/home" "$TEST_TMP/bin" "$TEST_TMP/dotfiles"
  : >"$TEST_TMP/log"
  : >"$TEST_TMP/claude-state"
  export HOME="$TEST_TMP/home" DOTFILES="$TEST_TMP/dotfiles"
  export PATH="$TEST_TMP/bin:/usr/bin:/bin"
  export TEST_LOG="$TEST_TMP/log" CLAUDE_STATE="$TEST_TMP/claude-state"
  export TB_STATE="$TEST_TMP/tb-state"
  for pkg in agents opencode claude pi hermes zsh; do mkdir -p "$DOTFILES/$pkg"; done
  mkdir -p "$DOTFILES/agents/.agents/skills/terminal-browser-workflow" "$DOTFILES/agents/.agents/skills/browser-debugger" "$DOTFILES/agents/.local/bin"
  : >"$DOTFILES/agents/.agents/skills/terminal-browser-workflow/SKILL.md" "$DOTFILES/agents/.agents/skills/browser-debugger/SKILL.md"
  printf '#!/usr/bin/env bash\n' >"$DOTFILES/agents/.local/bin/tmux-browser"
  printf '#!/usr/bin/env bash\n' >"$DOTFILES/agents/.local/bin/tmux-browser-cleanup"
  printf '#!/usr/bin/env bash\n' >"$DOTFILES/agents/.local/bin/plannotator-terminal-browser"
  chmod +x "$DOTFILES/agents/.local/bin/tmux-browser" "$DOTFILES/agents/.local/bin/tmux-browser-cleanup" "$DOTFILES/agents/.local/bin/plannotator-terminal-browser"
  mkdir -p "$DOTFILES/opencode/.config/opencode/agents" "$DOTFILES/opencode/.config/opencode"
  : >"$DOTFILES/opencode/.config/opencode/agents/browser-debugger.md"; printf '{}\n' >"$DOTFILES/opencode/.config/opencode/opencode.jsonc"
  mkdir -p "$DOTFILES/claude/.claude/agents"; : >"$DOTFILES/claude/.claude/agents/browser-debugger.md"
  mkdir -p "$DOTFILES/pi/.pi/agent/extensions"; : >"$DOTFILES/pi/.pi/agent/extensions/subagents.ts"
  mkdir -p "$DOTFILES/hermes/.hermes/skills/software-development/terminal-browser-workflow" "$DOTFILES/hermes/.hermes/skills/software-development/browser-debugger"
  : >"$DOTFILES/hermes/.hermes/SOUL.md" "$DOTFILES/hermes/.hermes/skills/software-development/terminal-browser-workflow/SKILL.md" "$DOTFILES/hermes/.hermes/skills/software-development/browser-debugger/SKILL.md"
}

install_fakes() {
  cat >"$TEST_TMP/bin/terminal-browser" <<'EOF'
#!/usr/bin/env bash
printf 'terminal-browser %s\n' "$*" >>"$TEST_LOG"
case "${1:-}" in
  upgrade) if [[ "${TB_UPGRADE_FAIL:-0}" == 1 ]]; then exit 23; fi ;;
  setup) if [[ "${TB_SETUP_FAIL:-0}" == 1 ]]; then exit 24; fi; mkdir -p "$HOME/.agents/skills/terminal-browser"; if [[ "${TB_OMIT_VENDOR:-0}" != 1 ]]; then : >"$HOME/.agents/skills/terminal-browser/SKILL.md"; fi ;;
esac
exit 0
EOF
  cat >"$TEST_TMP/bin/claude" <<'EOF'
#!/usr/bin/env bash
printf 'claude %s\n' "$*" >>"$TEST_LOG"
if [[ "${CLAUDE_FAIL_GET:-0}" == 1 && "${1:-}" == mcp && "${2:-}" == get ]]; then printf 'backend unavailable\n'; exit 41; fi
if [[ "${CLAUDE_FAIL_REMOVE:-0}" == 1 && "${1:-}" == mcp && "${2:-}" == remove ]]; then printf 'remove failed\n'; exit 42; fi
if [[ "${CLAUDE_FAIL_ADD:-0}" == 1 && "${1:-}" == mcp && "${2:-}" == add ]]; then printf 'add failed\n'; exit 43; fi
if [[ "${1:-}" == mcp && "${2:-}" == get ]]; then
  grep -Fxq "${3:-}" "$CLAUDE_STATE" && { printf '%s: configured\n' "$3"; exit 0; }
  printf 'No MCP server named "%s".\n' "$3"; exit 1
fi
  if [[ "${1:-}" == mcp && "${2:-}" == remove ]]; then sed -i "\|^${5:-}$|d" "$CLAUDE_STATE"; fi
  if [[ "${1:-}" == mcp && "${2:-}" == add ]]; then printf '%s\n' "${7:-}" >>"$CLAUDE_STATE"; fi
EOF
  cat >"$TEST_TMP/bin/stow" <<'EOF'
#!/usr/bin/env bash
printf 'stow %s\n' "$*" >>"$TEST_LOG"
[[ "${STOW_FAIL:-0}" == 1 ]] && exit 31
omit() { case ",${STOW_OMIT:-}," in *",$1,"*) return 0;; esac; return 1; }
bad_target() { case ",${STOW_BAD_TARGET:-}," in *",$1,"*) return 0;; esac; return 1; }
for pkg in "$@"; do case "$pkg" in
  agents) omit canonical || { mkdir -p "$HOME/.agents/skills"; if [[ "${STOW_BAD_TARGET:-}" == canonical ]]; then ln -sfn "$DOTFILES/claude/.claude/agents" "$HOME/.agents/skills/terminal-browser-workflow"; else ln -sfn "$DOTFILES/agents/.agents/skills/terminal-browser-workflow" "$HOME/.agents/skills/terminal-browser-workflow"; fi; ln -sfn "$DOTFILES/agents/.agents/skills/browser-debugger" "$HOME/.agents/skills/browser-debugger"; }; omit launcher || { mkdir -p "$HOME/.local/bin"; ln -sfn "$DOTFILES/agents/.local/bin/tmux-browser" "$HOME/.local/bin/tmux-browser"; [[ "${STOW_NONEXEC:-}" == launcher ]] && chmod a-x "$HOME/.local/bin/tmux-browser"; }; omit cleanup || { mkdir -p "$HOME/.local/bin"; if [[ "${STOW_BAD_TARGET:-}" == cleanup ]]; then ln -sfn "$DOTFILES/claude/.claude/agents/browser-debugger.md" "$HOME/.local/bin/tmux-browser-cleanup"; else ln -sfn "$DOTFILES/agents/.local/bin/tmux-browser-cleanup" "$HOME/.local/bin/tmux-browser-cleanup"; fi; [[ "${STOW_NONEXEC:-}" == cleanup ]] && chmod a-x "$HOME/.local/bin/tmux-browser-cleanup"; }; omit plannotator-adapter || { mkdir -p "$HOME/.local/bin"; if [[ "${STOW_BAD_TARGET:-}" == plannotator-adapter ]]; then ln -sfn "$DOTFILES/claude/.claude/agents/browser-debugger.md" "$HOME/.local/bin/plannotator-terminal-browser"; else ln -sfn "$DOTFILES/agents/.local/bin/plannotator-terminal-browser" "$HOME/.local/bin/plannotator-terminal-browser"; fi; [[ "${STOW_NONEXEC:-}" == plannotator-adapter ]] && chmod a-x "$HOME/.local/bin/plannotator-terminal-browser"; } ;;
  opencode) omit opencode-skills || { mkdir -p "$HOME/.config/opencode/skills"; ln -sfn "$DOTFILES/agents/.agents/skills/terminal-browser-workflow" "$HOME/.config/opencode/skills/terminal-browser-workflow"; ln -sfn "$DOTFILES/agents/.agents/skills/browser-debugger" "$HOME/.config/opencode/skills/browser-debugger"; }; omit opencode-agent || { mkdir -p "$HOME/.config/opencode/agents"; ln -sfn "$DOTFILES/opencode/.config/opencode/agents/browser-debugger.md" "$HOME/.config/opencode/agents/browser-debugger.md"; }; omit opencode-config || { mkdir -p "$HOME/.config/opencode"; ln -sfn "$DOTFILES/opencode/.config/opencode/opencode.jsonc" "$HOME/.config/opencode/opencode.jsonc"; } ;;
 claude) omit claude-skills || { mkdir -p "$HOME/.claude/skills"; ln -sfn "$DOTFILES/agents/.agents/skills/terminal-browser-workflow" "$HOME/.claude/skills/terminal-browser-workflow"; ln -sfn "$DOTFILES/agents/.agents/skills/browser-debugger" "$HOME/.claude/skills/browser-debugger"; }; omit claude-agent || { mkdir -p "$HOME/.claude/agents"; ln -sfn "$DOTFILES/claude/.claude/agents/browser-debugger.md" "$HOME/.claude/agents/browser-debugger.md"; } ;;
 pi) omit pi || { mkdir -p "$HOME/.pi/agent/extensions"; cp "$DOTFILES/pi/.pi/agent/extensions/subagents.ts" "$HOME/.pi/agent/extensions/subagents.ts"; } ;;
 hermes) omit hermes-skills || { mkdir -p "$HOME/.hermes/skills/software-development"; ln -sfn "$DOTFILES/agents/.agents/skills/terminal-browser-workflow" "$HOME/.hermes/skills/software-development/terminal-browser-workflow"; ln -sfn "$DOTFILES/agents/.agents/skills/browser-debugger" "$HOME/.hermes/skills/software-development/browser-debugger"; }; omit hermes-soul || { mkdir -p "$HOME/.hermes"; ln -sfn "$DOTFILES/hermes/.hermes/SOUL.md" "$HOME/.hermes/SOUL.md"; } ;;
 zsh) : ;;
 esac; done
EOF
  cat >"$TEST_TMP/bin/opencode" <<'EOF'
#!/usr/bin/env bash
printf 'opencode %s\n' "$*" >>"$TEST_LOG"
[[ "${OPENCODE_DEBUG_FAIL:-0}" == 1 ]] && { printf 'debug backend unavailable\n'; exit 46; }
case "${OPENCODE_RUNTIME_STATE:-clean}" in
  malformed) printf '{malformed\n' ;;
  chrome) printf '{"mcp":{"chrome-devtools":{}}}\n' ;;
  playwright) printf '{"mcp":{"playwright":{}}}\n' ;;
  *) printf '{"mcp":{"unrelated":{}}}\n' ;;
esac
EOF
  cat >"$TEST_TMP/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >>"$TEST_LOG"
[[ "${CURL_FAIL:-0}" == 1 ]] && exit 44
out=""
while (($#)); do
  if [[ "$1" == -o ]]; then out="$2"; shift 2; elif [[ "$1" == -o* ]]; then out="${1#-o}"; shift; else shift; fi
done
[[ -n "$out" ]] || exit 45
cat >"$out" <<'INSTALLER'
mkdir -p "$HOME/.local/bin" "$HOME/.agents/skills/terminal-browser"
cat >"$HOME/.local/bin/terminal-browser" <<'LAUNCHER'
#!/usr/bin/env bash
printf 'terminal-browser %s\n' "$*" >>"$TEST_LOG"
LAUNCHER
chmod +x "$HOME/.local/bin/terminal-browser"
: >"$HOME/.agents/skills/terminal-browser/SKILL.md"
INSTALLER
EOF
  printf '#!/usr/bin/env bash\nexit 0\n' >"$TEST_TMP/bin/rtk"
  cat >"$TEST_TMP/installer" <<'EOF'
#!/usr/bin/env bash
printf 'installer %s\n' "$*" >>"$TEST_LOG"
[[ "${INSTALLER_FAIL:-0}" == 1 ]] && exit 32
mkdir -p "$HOME/.local/bin" "$HOME/.agents/skills/terminal-browser"
cat >"$HOME/.local/bin/terminal-browser" <<'LAUNCHER'
#!/usr/bin/env bash
printf 'terminal-browser %s\n' "$*" >>"$TEST_LOG"
LAUNCHER
chmod +x "$HOME/.local/bin/terminal-browser"
[[ "${TB_OMIT_VENDOR:-0}" == 1 ]] || : >"$HOME/.agents/skills/terminal-browser/SKILL.md"
EOF
  chmod +x "$TEST_TMP/bin"/* "$TEST_TMP/installer"
}

run_fail() { if "$@" >/dev/null 2>&1; then return 1; fi; }

test_fresh_and_home_local_resolution() {
  new_fixture; install_fakes; rm "$TEST_TMP/bin/terminal-browser"
  if ! TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" >"$TEST_TMP/second-out" 2>&1; then
    while IFS= read -r line; do printf '%s\n' "$line"; done <"$TEST_TMP/second-out"
    return 1
  fi
  grep -Fq 'installer' "$TEST_LOG" || { printf 'installer log missing\n'; while IFS= read -r line; do printf '%s\n' "$line"; done <"$TEST_LOG"; return 1; }
  grep -Fxq 'terminal-browser setup' "$TEST_LOG" || { printf 'setup log missing\n'; while IFS= read -r line; do printf '%s\n' "$line"; done <"$TEST_LOG"; return 1; }
  new_fixture; install_fakes; mkdir -p "$HOME/.local/bin"; cp "$TEST_TMP/bin/terminal-browser" "$HOME/.local/bin/terminal-browser"; rm "$TEST_TMP/bin/terminal-browser"
  TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  grep -Fxq 'terminal-browser upgrade' "$TEST_LOG"
}

test_early_claude_skip() {
  new_fixture; install_fakes; rm "$TEST_TMP/bin/claude"
  output="$(TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT")"
  [[ "$output" == *'INFO: Claude unavailable; deferring browser MCP cleanup to claude-setup.sh'* ]]
}

test_terminal_setup_cleans_claude_browser_mcps() {
  new_fixture; install_fakes
  printf '%s\n' chrome-devtools playwright unrelated >"$CLAUDE_STATE"
  TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" >/dev/null
  ! grep -Fxq chrome-devtools "$CLAUDE_STATE"
  ! grep -Fxq playwright "$CLAUDE_STATE"
  grep -Fxq unrelated "$CLAUDE_STATE"
  grep -Fxq 'claude mcp remove --scope user chrome-devtools' "$TEST_LOG"
  grep -Fxq 'claude mcp remove --scope user playwright' "$TEST_LOG"
  ! grep -Fq 'claude mcp remove --scope user unrelated' "$TEST_LOG"
}

test_standalone_unmanaged_zsh_is_preserved() {
  new_fixture; install_fakes
  rm "$TEST_TMP/bin/stow"
  if ! PATH="$TEST_TMP/bin:/usr/bin:/bin" command -v stow >/dev/null 2>&1; then
    printf '%s\n' 'SKIP: GNU Stow unavailable; standalone unmanaged zsh test skipped'
    return 0
  fi
  mkdir -p "$DOTFILES/zsh"
  printf 'managed zsh\n' >"$DOTFILES/zsh/.zshrc"
  printf 'user-owned zsh\n' >"$HOME/.zshrc"
  cp "$HOME/.zshrc" "$TEST_TMP/zsh-before"
  if output="$(TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" 2>&1)"; then
    printf '%s\n' 'standalone setup unexpectedly replaced unmanaged zsh config'
    return 1
  fi
  [[ "$output" == *'cannot stow'* ]] || { printf '%s\n' "$output"; return 1; }
  cmp -s "$HOME/.zshrc" "$TEST_TMP/zsh-before"
  [[ -f "$HOME/.zshrc" && ! -L "$HOME/.zshrc" ]]
  printf '%s\n' 'PASS: standalone unmanaged zsh preserved byte-for-byte after GNU Stow conflict'
}

test_url_and_rejections() {
  new_fixture; install_fakes; rm "$TEST_TMP/bin/terminal-browser"
  TERMINAL_BROWSER_INSTALLER=https://example.invalid/install "$SUT"
  grep -Fq 'curl ' "$TEST_LOG"; grep -Fq 'https://example.invalid/install' "$TEST_LOG"; grep -Fq -- '--proto' "$TEST_LOG"; grep -Fq -- 'tlsv1.2' "$TEST_LOG"; grep -Fq -- '-o ' "$TEST_LOG"
  new_fixture; install_fakes; rm "$TEST_TMP/bin/terminal-browser"; run_fail env TERMINAL_BROWSER_INSTALLER=http://example.invalid/install "$SUT"
  new_fixture; install_fakes; rm "$TEST_TMP/bin/terminal-browser"; mkdir -p "$TEST_TMP/installer-dir"; run_fail env TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer-dir" "$SUT"
  new_fixture; install_fakes; rm "$TEST_TMP/bin/terminal-browser"; run_fail env TERMINAL_BROWSER_INSTALLER=file:///tmp/install "$SUT"
}

test_failures_propagate() {
  for vars in 'INSTALLER_FAIL=1' 'CURL_FAIL=1' 'TB_UPGRADE_FAIL=1' 'TB_SETUP_FAIL=1' 'STOW_FAIL=1' 'CLAUDE_FAIL_GET=1' 'CLAUDE_FAIL_REMOVE=1'; do
    new_fixture; install_fakes
    [[ "$vars" == CURL_FAIL=* || "$vars" == INSTALLER_FAIL=* ]] && rm "$TEST_TMP/bin/terminal-browser"
    [[ "$vars" == CLAUDE_FAIL_REMOVE=* ]] && printf 'chrome-devtools\n' >"$CLAUDE_STATE"
    if [[ "$vars" == CURL_FAIL=* ]]; then run_fail env "$vars" TERMINAL_BROWSER_INSTALLER=https://example.invalid/install "$SUT"; else run_fail env "$vars" TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"; fi
  done
}

test_verification_matrix() {
  for omission in canonical launcher cleanup plannotator-adapter opencode-skills opencode-agent claude-skills claude-agent pi hermes-skills hermes-soul; do
    new_fixture; install_fakes
    run_fail env STOW_OMIT="$omission" TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  done
  new_fixture; install_fakes; run_fail env TB_OMIT_VENDOR=1 TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; printf '  "chrome-devtools": {}\n' >"$DOTFILES/opencode/.config/opencode/opencode.jsonc"; run_fail env TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; run_fail env STOW_BAD_TARGET=canonical TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; run_fail env STOW_BAD_TARGET=cleanup TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; run_fail env STOW_NONEXEC=cleanup TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; run_fail env STOW_NONEXEC=launcher TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; run_fail env STOW_BAD_TARGET=plannotator-adapter TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  new_fixture; install_fakes; run_fail env STOW_NONEXEC=plannotator-adapter TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
}

test_final_verification() {
  new_fixture; install_fakes; TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT"
  TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" --verify-only
  rm "$TEST_TMP/bin/claude"; run_fail "$SUT" --verify-only
  new_fixture; install_fakes; TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" >/dev/null 2>&1; printf 'chrome-devtools\n' >"$CLAUDE_STATE"; run_fail "$SUT" --verify-only
}

test_opencode_runtime_verification() {
  for state in clean chrome playwright; do
    new_fixture; install_fakes; TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" >/dev/null
    if [[ "$state" == clean ]]; then
      if ! output="$(TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" --verify-only 2>&1)"; then
        printf '%s\n' "$output" >&2
        return 1
      fi
      if ! grep -Fxq 'opencode debug config' "$TEST_LOG"; then
        while IFS= read -r line; do printf 'runtime log: %s\n' "$line"; done <"$TEST_LOG"
        return 1
      fi
    else
      run_fail env OPENCODE_RUNTIME_STATE="$state" "$SUT" --verify-only
    fi
  done
  new_fixture; install_fakes; TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" >/dev/null
  run_fail env OPENCODE_DEBUG_FAIL=1 "$SUT" --verify-only
  new_fixture; install_fakes; TERMINAL_BROWSER_INSTALLER="$TEST_TMP/installer" "$SUT" >/dev/null
  run_fail env OPENCODE_RUNTIME_STATE=malformed "$SUT" --verify-only
}

test_claude_setup() {
  new_fixture; install_fakes; mkdir -p "$HOME/.claude"; : >"$HOME/.claude/.credentials.json"
  printf '%s\n' chrome-devtools playwright unrelated >"$CLAUDE_STATE"; "$ROOT_DIR/claude-setup.sh" >/dev/null
  ! grep -Fxq chrome-devtools "$CLAUDE_STATE"; ! grep -Fxq playwright "$CLAUDE_STATE"; grep -Fxq unrelated "$CLAUDE_STATE"
  grep -Fxq betterstack "$CLAUDE_STATE"; grep -Fxq composio "$CLAUDE_STATE"; "$ROOT_DIR/claude-setup.sh" >/dev/null
  [[ "$(grep -Fc betterstack "$CLAUDE_STATE")" == 1 && "$(grep -Fc composio "$CLAUDE_STATE")" == 1 ]]
  for failure in get add remove; do
    new_fixture; install_fakes; mkdir -p "$HOME/.claude"; : >"$HOME/.claude/.credentials.json"
    [[ "$failure" == remove ]] && printf 'chrome-devtools\n' >"$CLAUDE_STATE"
    run_fail env "CLAUDE_FAIL_${failure^^}=1" "$ROOT_DIR/claude-setup.sh"
  done
}

test_fresh_and_home_local_resolution; test_early_claude_skip; test_terminal_setup_cleans_claude_browser_mcps; test_standalone_unmanaged_zsh_is_preserved; test_url_and_rejections; test_failures_propagate; test_verification_matrix; test_final_verification; test_opencode_runtime_verification; test_claude_setup
printf 'PASS: terminal-browser quality contract tests\n'
