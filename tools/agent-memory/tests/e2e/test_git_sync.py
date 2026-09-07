import json
import os
import subprocess
import sys

import pytest


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=check)


def memory(repo, env, *args, input=None):
    completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args], env={**os.environ, **env},
                               input=input, text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)["result"]


@pytest.fixture
def git_fixture(tmp_path):
    repo, remote = tmp_path / "repo", tmp_path / "remote.git"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "README").write_text("base", encoding="utf-8")
    git(repo, "add", "README")
    git(repo, "commit", "-m", "base")
    subprocess.run(["git", "init", "--bare", str(remote)], text=True, capture_output=True, check=True)
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "main")
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"),
           "AGENT_MEMORY_VAULT": str(repo / "agents/.agents/memory"), "AGENT_MEMORY_REPO": str(repo)}
    return repo, remote, env


def test_sync_commits_only_memory_and_preserves_user_index(git_fixture):
    repo, remote, env = git_fixture
    (repo / "opencode").mkdir()
    (repo / "opencode/config.jsonc").write_text("staged-user-change", encoding="utf-8")
    git(repo, "add", "opencode/config.jsonc")
    (repo / "pi").mkdir()
    (repo / "pi/extension.ts").write_text("unstaged-user-change", encoding="utf-8")
    before_index = git(repo, "write-tree").stdout
    created = memory(repo, env, "add", "--request-id", "a", "--type", "fact", "--scope", "global", "--content", "a")
    report = memory(repo, env, "worker", "--drain")
    assert report["sync"]["commit_created"] is True
    assert git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.splitlines() == ["agents/.agents/memory/notes/" + created["id"] + ".md"]
    assert git(repo, "write-tree").stdout == before_index
    assert (repo / "pi/extension.ts").read_text(encoding="utf-8") == "unstaged-user-change"
    assert git(remote, "rev-parse", "main").stdout == git(repo, "rev-parse", "HEAD").stdout


def test_sync_discovers_direct_edits_and_retains_retryable_failures(git_fixture):
    repo, remote, env = git_fixture
    created = memory(repo, env, "add", "--request-id", "direct", "--type", "fact", "--scope", "global", "--content", "original")
    note = repo / "agents/.agents/memory/notes" / f"{created['id']}.md"
    note.write_text(note.read_text(encoding="utf-8").replace("original", "edited"), encoding="utf-8")
    report = memory(repo, env, "worker", "--once")
    assert report["sync"]["commit_created"] is True
    assert report["sync"]["reconciled"] is True

    peer = repo.parent / "peer"
    subprocess.run(["git", "clone", str(remote), str(peer)], text=True, capture_output=True, check=True)
    git(peer, "config", "user.email", "test@example.invalid")
    git(peer, "config", "user.name", "Test")
    (peer / "peer").write_text("ahead", encoding="utf-8")
    git(peer, "add", "peer")
    git(peer, "commit", "-m", "peer ahead")
    git(peer, "push")
    memory(repo, env, "add", "--request-id", "retry", "--type", "fact", "--scope", "global", "--content", "retry")
    failed = memory(repo, env, "worker", "--drain")
    assert failed["retrying"] >= 1
    assert list((tmp_path := repo.parent / "state" / "outbox" / "ready").glob("*.json"))


def test_sync_pause_and_index_lock_retain_work(git_fixture):
    repo, _, env = git_fixture
    memory(repo, env, "sync", "pause", "--reason", "maintenance")
    paused = memory(repo, env, "status")
    assert paused["sync_paused"]["reason"] == "maintenance"
    memory(repo, env, "add", "--request-id", "paused", "--type", "fact", "--scope", "global", "--content", "paused write")
    assert memory(repo, env, "worker", "--drain")["sync"]["paused"] is True
    memory(repo, env, "sync", "resume")
    (repo / ".git/index.lock").write_text("synthetic lock", encoding="utf-8")
    retained = memory(repo, env, "worker", "--drain")
    assert retained["retrying"] >= 1
    assert list((repo.parent / "state" / "outbox" / "ready").glob("*.json"))
