import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from uuid import UUID

import pytest


@pytest.fixture
def run_cli():
    def run(env, *args, check=True):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_memory.cli", *args],
            env={key: value for key, value in {**os.environ, **env}.items()
                 if key not in {"AGENT_MEMORY_HOME", "AGENT_MEMORY_VAULT"} or key in env},
            text=True,
            capture_output=True,
        )
        if check:
            assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    return run


class McpClient:
    def __init__(self, env):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "agent_memory.mcp_server"],
            env={**os.environ, **env},
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.request_id = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.process.terminate()
        self.process.wait(timeout=5)

    def _call(self, name, arguments):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": self.request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            assert self.process.stderr
            pytest.fail(self.process.stderr.read())
        response = json.loads(line)
        return response

    def call(self, name, arguments):
        response = self._call(name, arguments)
        assert "error" not in response
        return json.loads(response["result"]["content"][0]["text"])

    def call_error(self, name, arguments):
        response = self._call(name, arguments)
        assert "error" in response
        return response["error"]["data"]


@pytest.fixture
def mcp_client():
    @contextmanager
    def create(env):
        with McpClient(env) as client:
            yield client

    return create


def test_cli_and_mcp_share_one_canonical_record(tmp_path, run_cli, mcp_client):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"),
           "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    created = run_cli(env, "add", "--request-id", "req-1", "--type", "decision",
                      "--scope", "project", "--project", "dotfiles",
                      "--content", "Use one canonical local memory vault.")
    replayed = run_cli(env, "add", "--request-id", "req-1", "--type", "decision",
                       "--scope", "project", "--project", "dotfiles",
                       "--content", "Use one canonical local memory vault.")
    assert replayed["result"]["id"] == created["result"]["id"]
    assert UUID(created["result"]["id"]).version == 7
    note = tmp_path / "vault" / "notes" / f"{created['result']['id']}.md"
    assert note.is_file()
    assert note.read_text(encoding="utf-8").startswith("---\n")
    assert 'status: "active"' in note.read_text(encoding="utf-8")
    with sqlite3.connect(tmp_path / "state" / "memory.sqlite3") as catalog:
        assert catalog.execute("SELECT id, status FROM memories").fetchall() == [
            (created["result"]["id"], "active")]
        catalog.execute("DELETE FROM idempotency WHERE request_id = 'req-1'")
    replayed_after_index_loss = run_cli(env, "add", "--request-id", "req-1", "--type", "decision",
                                        "--scope", "project", "--project", "dotfiles",
                                        "--content", "Use one canonical local memory vault.")
    assert replayed_after_index_loss["result"] == created["result"]

    with mcp_client(env) as mcp:
        found = mcp.call("memory_search", {"query": "canonical vault", "project": "dotfiles"})
        assert [m["id"] for m in found["memories"]] == [created["result"]["id"]]
        current = mcp.call("memory_get", {"id": created["result"]["id"]})
        changed = mcp.call("memory_update", {
            "id": current["id"], "expected_revision": current["revision"],
            "expected_content_hash": current["content_hash"],
            "content": "Use one canonical, Git-backed local memory vault.",
            "request_id": "req-2",
        })
        assert changed["revision"] == 2
        stale = mcp.call_error("memory_update", {
            "id": current["id"], "expected_revision": 1,
            "expected_content_hash": current["content_hash"],
            "content": "overwrite", "request_id": "req-3",
        })
        assert stale["code"] == "revision_conflict"
        listed = mcp.call("memory_list", {"project": "dotfiles"})
        assert [m["id"] for m in listed["memories"]] == [changed["id"]]
        deleted = mcp.call("memory_delete", {
            "id": changed["id"], "expected_revision": 2,
            "expected_content_hash": changed["content_hash"], "request_id": "req-4",
        })
        assert deleted["status"] == "deleted"
        assert not note.exists()
        journal = [json.loads(line) for line in (tmp_path / "state" / "mutations.jsonl").read_text().splitlines()]
        assert journal[-1]["operation"] == "delete"
        assert journal[-1]["id"] == changed["id"]
        assert journal[-1]["revision"] == 2
        assert journal[-1]["content_hash"] == changed["content_hash"]
        assert journal[-1]["status"] == "deleted"
        assert mcp.call("memory_search", {"query": "Git-backed", "project": "dotfiles"})["memories"] == []
        replay_after_delete = mcp.call("memory_add", {
            "request_id": "req-1", "type": "decision", "scope": "project",
            "project": "dotfiles", "content": "Use one canonical local memory vault.",
        })
        assert replay_after_delete == created["result"]

    invalid_type = run_cli(env, "add", "--request-id", "req-invalid-type", "--type", "unknown",
                           "--scope", "project", "--content", "invalid", check=False)
    assert invalid_type["error"]["code"] == "invalid_type"
    invalid_scope = run_cli(env, "add", "--request-id", "req-invalid-scope", "--type", "decision",
                            "--scope", "session", "--content", "invalid", check=False)
    assert invalid_scope["error"]["code"] == "invalid_scope"


def test_cli_uses_canonical_default_paths(tmp_path, run_cli):
    home = tmp_path / "home"
    created = run_cli({"HOME": str(home)}, "add", "--request-id", "req-default-paths",
                      "--type", "fact", "--scope", "global", "--content", "Defaults are canonical.")

    assert (home / ".agents" / "memory" / "notes" / f"{created['result']['id']}.md").is_file()
    assert (home / ".local" / "share" / "agent-memory" / "memory.sqlite3").is_file()
    current = run_cli({"HOME": str(home)}, "get", "--id", created["result"]["id"])["result"]
    superseded = run_cli(
        {"HOME": str(home)}, "update", "--id", current["id"],
        "--expected-revision", str(current["revision"]),
        "--expected-content-hash", current["content_hash"], "--request-id", "req-supersede",
        "--status", "superseded",
    )["result"]
    assert superseded["status"] == "superseded"
    with sqlite3.connect(home / ".local" / "share" / "agent-memory" / "memory.sqlite3") as catalog:
        assert catalog.execute("SELECT status FROM memories").fetchone() == ("superseded",)
