from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import frontmatter


VAULT_RELPATH = Path("agents/.agents/memory")


@dataclass(frozen=True)
class SyncReport:
    commit_created: bool = False
    pushed: bool = False
    reconciled: bool = False
    error: str | None = None
    retryable: bool = False
    restoration_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class GitSync:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path

    @staticmethod
    def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(("git", *args), cwd=repo, text=True, capture_output=True, check=check)

    @staticmethod
    def _valid_vault_relpath(path: Path) -> bool:
        return not path.is_absolute() and path.parts == VAULT_RELPATH.parts

    def _unsafe_state(self, repo: Path) -> str | None:
        git_dir = Path(self._git(repo, "rev-parse", "--git-dir").stdout.strip())
        if not git_dir.is_absolute():
            git_dir = repo / git_dir
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply", "index.lock"):
            if (git_dir / name).exists():
                return name
        return None

    @staticmethod
    def _worktree_snapshot(repo: Path, vault: Path) -> dict[str, tuple]:
        snapshot = {}
        for path in repo.rglob("*"):
            if ".git" in path.parts or path.is_relative_to(vault):
                continue
            stat = path.lstat()
            relative = str(path.relative_to(repo))
            if path.is_symlink():
                snapshot[relative] = ("symlink", stat.st_mode, os.readlink(path))
            elif path.is_file():
                snapshot[relative] = ("file", stat.st_mode, hashlib.sha256(path.read_bytes()).hexdigest())
            elif path.is_dir():
                snapshot[relative] = ("directory", stat.st_mode)
        return snapshot

    def _push_upstream(self, repo: Path) -> subprocess.CompletedProcess:
        branch = self._git(repo, "branch", "--show-current").stdout.strip()
        remote = self._git(repo, "config", f"branch.{branch}.remote").stdout.strip()
        merge = self._git(repo, "config", f"branch.{branch}.merge").stdout.strip()
        if not remote or not merge.startswith("refs/heads/"):
            raise ValueError("current branch has no tracking branch")
        return self._git(repo, "push", remote, f"HEAD:{merge}", check=False)

    def run(self, repo: Path, vault_relpath: Path, reconcile: Callable[[], object] | None = None) -> SyncReport:
        vault_relpath = Path(vault_relpath)
        if not self._valid_vault_relpath(vault_relpath):
            return SyncReport(error="invalid vault path", retryable=False)
        repo = repo.resolve()
        vault = repo / vault_relpath
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Reconciliation owns the same mutation lock and may repair canonical paths.
        # Do it before taking the Git critical section to avoid self-deadlocking flock.
        reconciled = reconcile() if reconcile else None
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            before_index = None
            index_touched = False
            commit_created = False
            try:
                unsafe = self._unsafe_state(repo)
                if unsafe:
                    return SyncReport(error=f"unsafe git state: {unsafe}", retryable=True)
                changed = self._git(repo, "status", "--porcelain=v1", "--", str(vault_relpath)).stdout.splitlines()
                for line in changed:
                    path = repo / line[3:]
                    if path.suffix == ".md" and path.exists():
                        frontmatter.load(path.read_text(encoding="utf-8"))
                before_index = self._git(repo, "write-tree").stdout.strip()
                before_worktree = self._worktree_snapshot(repo, vault)
                if changed:
                    self._git(repo, "add", "--intent-to-add", "--", str(vault_relpath))
                    index_touched = True
                    committed = self._git(repo, "commit", "--only", "-m", "chore(memory): persist curated memory", "--", str(vault_relpath), check=False)
                    if committed.returncode:
                        restored = self._git(repo, "restore", "--staged", f"--source={before_index}", "--", str(vault_relpath), check=False)
                        index_touched = False
                        return SyncReport(error=committed.stderr.strip() or committed.stdout.strip(), retryable=True,
                                          restoration_error=(restored.stderr.strip() or restored.stdout.strip()) if restored.returncode else None)
                    commit_created = True
                    restored = self._git(repo, "restore", "--staged", f"--source={before_index}", "--", str(vault_relpath), check=False)
                    if restored.returncode:
                        return SyncReport(commit_created, error="index restoration failed", retryable=True,
                                          restoration_error=restored.stderr.strip() or restored.stdout.strip())
                    index_touched = False
                if self._git(repo, "write-tree").stdout.strip() != before_index or self._worktree_snapshot(repo, vault) != before_worktree:
                    return SyncReport(commit_created, error="unrelated Git index or worktree changed", retryable=True)
                pushed = self._push_upstream(repo)
                if pushed.returncode:
                    return SyncReport(commit_created, error=pushed.stderr.strip() or pushed.stdout.strip(), retryable=True)
                return SyncReport(commit_created, True, bool(getattr(reconciled, "external_edits", [])))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                return SyncReport(commit_created, error=str(error), retryable=True)
            finally:
                restoration_error = None
                if index_touched and before_index:
                    restored = self._git(repo, "restore", "--staged", f"--source={before_index}", "--", str(vault_relpath), check=False)
                    if restored.returncode:
                        restoration_error = restored.stderr.strip() or restored.stdout.strip()
                fcntl.flock(lock, fcntl.LOCK_UN)
