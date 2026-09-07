import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeOllama:
    def __init__(self):
        vectors = {
            "prefer concise status updates.": [0.0, 1.0],
            "store memory in dotfiles.": [1.0, 0.0],
            "where should memory live": [1.0, 0.0],
            "memory dotfiles": [1.0, 0.0],
        }

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                texts = request.get("input", request.get("texts", []))
                response = {"embeddings": [vectors.get(text.lower(), [0.0, 0.0]) for text in texts]}
                encoded = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def fake_ollama():
    fake = FakeOllama()
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture
def memory_app(tmp_path, fake_ollama):
    env = {
        "AGENT_MEMORY_HOME": str(tmp_path / "state"),
        "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
        "OLLAMA_URL": fake_ollama.url,
    }

    def run(*args, check=True):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_memory.cli", *args],
            env={**os.environ, **env}, text=True, capture_output=True, timeout=10,
        )
        assert completed.stdout, completed.stderr
        payload = json.loads(completed.stdout)
        if check:
            assert completed.returncode == 0, completed.stderr
            assert payload["ok"]
            return payload["result"]
        return payload

    return run


class McpClient:
    def __init__(self, env):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "agent_memory.mcp_server"], env={**os.environ, **env},
            text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.request_id = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.process.terminate()
        self.process.wait(timeout=5)

    def call(self, name, arguments):
        self.request_id += 1
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.request_id,
            "method": "tools/call", "params": {"name": name, "arguments": arguments}}) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        assert "error" not in response, response
        return json.loads(response["result"]["content"][0]["text"])


def test_hybrid_search_degrades_to_fts_without_losing_results(memory_app, fake_ollama, tmp_path):
    global_memory = memory_app("add", "--request-id", "global", "--type", "preference",
                               "--scope", "global", "--content", "Prefer concise status updates.")
    project = memory_app("add", "--request-id", "project", "--type", "decision", "--scope",
                         "project", "--project", "dotfiles", "--content", "Store memory in dotfiles.")
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": fake_ollama.url}
    with McpClient(env) as mcp:
        pinned = mcp.call("memory_pin", {"id": project["id"], "request_id": "pin",
            "expected_revision": project["revision"], "expected_content_hash": project["content_hash"], "pinned": True})
        assert pinned["pinned"] is True
        feedback = mcp.call("memory_feedback", {"id": project["id"], "request_id": "feedback", "rating": "positive"})
        assert feedback == {"id": project["id"], "positive": 1, "negative": 0}
        moved = mcp.call("memory_scope", {"id": global_memory["id"], "request_id": "scope",
            "expected_revision": global_memory["revision"], "expected_content_hash": global_memory["content_hash"],
            "scope": "project", "project": "dotfiles"})
        assert moved["scope"] == "project"
    ranked = memory_app("search", "--query", "where should memory live", "--project", "dotfiles")
    assert ranked["semantic_status"] == "available"
    assert ranked["memories"][0]["id"] == project["id"]
    assert "project_exact" in ranked["memories"][0]["boosts"]
    assert ranked["memories"][0]["semantic_rank"] == 1
    assert "rrf" in ranked["memories"][0]["explanation"]
    assert memory_app("search", "--query", "memory", "--scope", "project", "--type", "decision", "--tag", "missing")["memories"] == []
    fake_ollama.stop()
    degraded = memory_app("search", "--query", "memory dotfiles", "--project", "dotfiles")
    assert degraded["semantic_status"] == "unavailable"
    assert degraded["memories"][0]["id"] == project["id"]


def test_mcp_exposes_lifecycle_tools_but_not_authorize(memory_app, fake_ollama, tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": fake_ollama.url}
    with McpClient(env) as mcp:
        mcp.request_id += 1
        assert mcp.process.stdin and mcp.process.stdout
        mcp.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mcp.request_id, "method": "tools/list"}) + "\n")
        mcp.process.stdin.flush()
        names = {tool["name"] for tool in json.loads(mcp.process.stdout.readline())["result"]["tools"]}
    assert {"memory_feedback", "memory_pin", "memory_scope", "memory_rebuild", "memory_reconcile",
            "memory_maintain", "memory_delete_all", "memory_purge"} <= names
    assert "memory_admin_authorize" not in names
