import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from uuid import UUID

import pytest

from agent_memory.capture import Outbox


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
    note = tmp_path / "vault" / "Projects" / "dotfiles" / f"{created['result']['id']}.md"
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

    assert (home / ".agents" / "memory" / "Global" / f"{created['result']['id']}.md").is_file()
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


def test_cli_upgrades_legacy_task_one_storage(tmp_path, run_cli):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"),
           "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    legacy_id = "018f6f0e-7f52-7dc9-a1f7-2f2872fa9c4a"
    notes = tmp_path / "vault" / "notes"
    notes.mkdir(parents=True)
    (notes / f"{legacy_id}.md").write_text(f'''---
id: "{legacy_id}"
type: "decision"
scope: "project"
project: "dotfiles"
importance: 0.8
confidence: 0.95
pinned: false
tags: ["legacy"]
revision: 1
content_hash: "legacy-hash"
created_at: "2026-09-07T12:00:00Z"
updated_at: "2026-09-07T12:00:00Z"
---

Legacy Task 1 note.
''', encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    with sqlite3.connect(state / "memory.sqlite3") as catalog:
        catalog.executescript("""
            CREATE TABLE memories (
                id TEXT PRIMARY KEY, type TEXT NOT NULL, scope TEXT NOT NULL,
                project TEXT, content TEXT NOT NULL, importance REAL NOT NULL,
                confidence REAL NOT NULL, pinned INTEGER NOT NULL, tags TEXT NOT NULL,
                revision INTEGER NOT NULL, content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE memories_fts USING fts5(id UNINDEXED, content);
            CREATE TABLE idempotency (
                request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result_id TEXT NOT NULL
            );
        """)
        catalog.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (legacy_id, "decision", "project", "dotfiles", "Legacy Task 1 note.",
                         0.8, 0.95, 0, "legacy", 1, "legacy-hash",
                         "2026-09-07T12:00:00Z", "2026-09-07T12:00:00Z"))
        catalog.execute("INSERT INTO memories_fts VALUES (?, ?)", (legacy_id, "Legacy Task 1 note."))
        catalog.execute("INSERT INTO idempotency VALUES (?, ?, ?)",
                        ("legacy-request", "legacy-payload", legacy_id))

    listed = run_cli(env, "list", "--project", "dotfiles")["result"]["memories"]
    assert listed == [{
        "id": legacy_id, "type": "decision", "scope": "project", "project": "dotfiles",
        "content": "Legacy Task 1 note.", "importance": 0.8, "confidence": 0.95,
        "pinned": False, "tags": ["legacy"], "status": "active", "revision": 1,
        "content_hash": "legacy-hash", "created_at": "2026-09-07T12:00:00Z",
        "updated_at": "2026-09-07T12:00:00Z", "source_client": "unknown", "source_session": "unknown", "supersedes": [],
    }]
    legacy = run_cli(env, "get", "--id", legacy_id)["result"]
    upgraded = run_cli(
        env, "update", "--id", legacy_id, "--expected-revision", "1",
        "--expected-content-hash", legacy["content_hash"], "--request-id", "upgrade-legacy",
        "--status", "superseded",
    )["result"]
    assert upgraded["status"] == "superseded"
    assert 'status: "superseded"' in (tmp_path / "vault" / "Projects" / "dotfiles" / f"{legacy_id}.md").read_text(encoding="utf-8")
    with sqlite3.connect(state / "memory.sqlite3") as catalog:
        assert {column[1] for column in catalog.execute("PRAGMA table_info(memories)")} >= {"status"}
        assert {column[1] for column in catalog.execute("PRAGMA table_info(idempotency)")} >= {"result_json"}
        replay = json.loads(catalog.execute(
            "SELECT result_json FROM idempotency WHERE request_id = 'legacy-request'").fetchone()[0])
    assert replay["id"] == legacy_id
    assert replay["status"] == "active"


def test_require_healthy_rejects_ready_and_running_outbox_work(tmp_path, run_cli):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"),
           "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    outbox = Outbox(tmp_path / "state")
    outbox.enqueue("capture", {"id": "ready"})
    ready = run_cli(env, "status", "--require-healthy", check=False)
    assert ready["error"]["code"] == "unhealthy"
    claimed = outbox.claim()
    assert claimed is not None
    running = run_cli(env, "status", "--require-healthy", check=False)
    assert running["error"]["code"] == "unhealthy"
