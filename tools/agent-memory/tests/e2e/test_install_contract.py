import os
import stat
import subprocess
from pathlib import Path


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_clean_home_install_is_idempotent_and_does_not_require_mem0(tmp_path):
    root = Path(__file__).parents[4]
    dotfiles = root.parents[1] / "dotfiles-shared-agent-memory"
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls"
    bin_dir.mkdir()
    calls.touch()

    write_executable(bin_dir / "uv", f'''#!/usr/bin/env bash
set -euo pipefail
printf 'uv %s\\n' "$*" >> {calls!s}
[[ "$1" == sync && "$2" == --locked && "$3" == --project ]]
''')
    write_executable(bin_dir / "ollama", f'''#!/usr/bin/env bash
set -euo pipefail
printf 'ollama %s\\n' "$*" >> {calls!s}
if [[ "$1" == list ]]; then
  [[ -f {tmp_path!s}/model-pulled ]] && printf 'nomic-embed-text latest\\n'
elif [[ "$1" == pull ]]; then
  touch {tmp_path!s}/model-pulled
else
  exit 1
fi
''')
    write_executable(bin_dir / "stow", f'''#!/usr/bin/env bash
set -euo pipefail
printf 'stow %s\\n' "$*" >> {calls!s}
target=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target=*) target="${{1#--target=}}" ;;
    --target) shift; target="$1" ;;
    --restow) ;;
    agents) mkdir -p "$target/.agents"; ln -sfn '{dotfiles}/agents/.agents/memory' "$target/.agents/memory" ;;
    systemd) mkdir -p "$target/.config/systemd/user"; ln -sfn '{dotfiles}/systemd/.config/systemd/user/agent-memory-worker.timer' "$target/.config/systemd/user/agent-memory-worker.timer" ;;
  esac
  shift
done
''')
    write_executable(bin_dir / "systemctl", f'''#!/usr/bin/env bash
set -euo pipefail
printf 'systemctl %s\\n' "$*" >> {calls!s}
[[ "$1" == --user ]]
''')

    env = {
        **os.environ,
        "HOME": str(home),
        "DOTFILES": str(dotfiles),
        "PATH": f"{bin_dir}:/usr/bin",
        "AGENT_MEMORY_HOME": str(home / ".local/share/agent-memory"),
        "AGENT_MEMORY_VAULT": str(home / ".agents/memory"),
    }
    setup = root / "agent-memory-setup.sh"
    first = subprocess.run([setup], env=env, text=True, capture_output=True)
    second = subprocess.run([setup], env=env, text=True, capture_output=True)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (home / ".agents/memory").is_symlink()
    assert (home / ".agents/memory").resolve() == dotfiles / "agents/.agents/memory"
    assert stat.S_IMODE((home / ".config/agent-memory").stat().st_mode) == 0o700
    assert stat.S_IMODE((home / ".local/share/agent-memory").stat().st_mode) == 0o700
    assert (home / ".local/bin/memoryctl").is_symlink()
    assert (home / ".local/bin/memoryctl").resolve() == root / "tools/agent-memory/.venv/bin/memoryctl"
    recorded = calls.read_text(encoding="utf-8")
    assert recorded.count("uv sync --locked --project") == 2
    assert recorded.count("ollama list") == 2
    assert recorded.count("ollama pull nomic-embed-text") == 1
    assert recorded.count("systemctl --user daemon-reload") == 2
    assert recorded.count("systemctl --user enable --now agent-memory-worker.timer") == 2
    assert "MEM0_API_KEY" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in (home / ".config/agent-memory").rglob("*")
        if path.is_file()
    )
    assert "MEM0_API_KEY" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in (home / ".local/share/agent-memory").rglob("*")
        if path.is_file() and path.suffix != ".sqlite3"
    )
    assert '"ok":true' in first.stdout
