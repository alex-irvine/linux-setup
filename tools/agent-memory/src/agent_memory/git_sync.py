from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from . import frontmatter


@dataclass(frozen=True)
class SyncReport:
    commit_created: bool = False
    pushed: bool = False
    reconciled: bool = False
    error: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class GitSync:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path

    @staticmethod
    def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(("git", *args), cwd=repo, text=True, capture_output=True, check=check)

    def _unsafe_state(self, repo: Path) -> str | None:
        git_dir = Path(self._git(repo, "rev-parse", "--git-dir").stdout.strip())
        if not git_dir.is_absolute():
            git_dir = repo / git_dir
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply", "index.lock"):
            if (git_dir / name).exists():
                return name
        return None

    @staticmethod
    def _worktree_hashes(repo: Path, vault: Path) -> dict[str, str]:
        hashes = {}
        for path in repo.rglob("*"):
            if not path.is_file() or ".git" in path.parts or path.is_relative_to(vault):
                continue
            hashes[str(path.relative_to(repo))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    def run(self, repo: Path, vault_relpath: Path) -> SyncReport:
        repo, vault_relpath = repo.resolve(), Path(vault_relpath)
        vault = repo / vault_relpath
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                unsafe = self._unsafe_state(repo)
                if unsafe:
                    return SyncReport(error=f"unsafe git state: {unsafe}", retryable=True)
                changed = self._git(repo, "status", "--porcelain=v1", "--", str(vault_relpath)).stdout.splitlines()
                for line in changed:
                    path = repo / line[3:]
                    if path.suffix == ".md" and path.exists():
                        frontmatter.load(path.read_text(encoding="utf-8"))
                before_index = self._git(repo, "write-tree").stdout
                before_worktree = self._worktree_hashes(repo, vault)
                commit_created = False
                if changed:
                    self._git(repo, "add", "--intent-to-add", "--", str(vault_relpath))
                    committed = self._git(repo, "commit", "--only", "-m", "chore(memory): persist curated memory", "--", str(vault_relpath), check=False)
                    if committed.returncode:
                        return SyncReport(error=committed.stderr.strip() or committed.stdout.strip(), retryable=True)
                    # --intent-to-add is required for new notes, but user staging stays exactly as it was.
                    self._git(repo, "restore", "--staged", f"--source={before_index.strip()}", "--", str(vault_relpath))
                    commit_created = True
                if self._git(repo, "write-tree").stdout != before_index or self._worktree_hashes(repo, vault) != before_worktree:
                    return SyncReport(commit_created, error="unrelated Git index or worktree changed", retryable=True)
                pushed = self._git(repo, "push", check=False)
                if pushed.returncode:
                    return SyncReport(commit_created, error=pushed.stderr.strip() or pushed.stdout.strip(), retryable=True)
                return SyncReport(commit_created, True)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                return SyncReport(error=str(error), retryable=True)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
