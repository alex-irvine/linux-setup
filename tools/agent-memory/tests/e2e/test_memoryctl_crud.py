import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest


@pytest.fixture
def run_cli():
    def run(env, *args):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_memory.cli", *args],
            env={**os.environ, **env},
            text=True,
            capture_output=True,
            check=True,
        )
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
        mcp.call("memory_delete", {
            "id": changed["id"], "expected_revision": 2,
            "expected_content_hash": changed["content_hash"], "request_id": "req-4",
        })
        assert mcp.call("memory_search", {"query": "Git-backed", "project": "dotfiles"})["memories"] == []
