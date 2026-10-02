import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_memory.ollama import DegradedStatus, EmbeddingBatch, OllamaClient


REVIEW = {"type": "fact", "scope": "global", "project": None, "content": "Completed migration; tests pass.",
          "importance": 0.5, "confidence": 0.95, "tags": ["ci"], "durability": True, "supersedes": []}


class _Server:
    def __init__(self, handler):
        self.paths, self.auth = [], []
        outer = self

        class Bound(handler):
            def log_message(self, *_):
                pass

            def do_GET(self):  # noqa: N802
                outer.paths.append(self.path)
                body = json.dumps(outer.get(self.path)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                outer.paths.append(self.path)
                outer.auth.append(self.headers.get("Authorization"))
                length = int(self.headers.get("Content-Length", 0))
                request = json.loads(self.rfile.read(length)) if length else {}
                body = json.dumps(outer.post(self.path, request)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Bound)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class FakeFallback(_Server):
    def __init__(self, review=None):
        self.review = review or REVIEW
        super().__init__(BaseHTTPRequestHandler)

    def post(self, path, request):
        if path.endswith("/chat/completions"):
            prompt = " ".join(message.get("content", "") for message in request.get("messages", []))
            if '"relation"' in prompt:
                return {"choices": [{"message": {"content": json.dumps({"relation": "distinct"})}}]}
            return {"choices": [{"message": {"content": json.dumps(self.review)}}]}
        if path.endswith("/embeddings"):
            return {"data": [{"embedding": [0.5, 0.25] * 384} for _ in request.get("input", [])]}
        return {"error": "unexpected path"}

    def get(self, path):
        return {"error": "unexpected path"}


class FakePrimary(_Server):
    def __init__(self, generate_response=None, vectors=None):
        self.generate_response = generate_response
        self.vectors = vectors or [[1.0, 0.0]]
        super().__init__(BaseHTTPRequestHandler)

    def get(self, path):
        return {"models": []}

    def post(self, path, request):
        if path.endswith("/api/generate"):
            return {"response": self.generate_response if self.generate_response is not None else json.dumps(REVIEW)}
        if path.endswith("/api/embed"):
            return {"embeddings": self.vectors}
        return {"error": "unexpected path"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OLLAMA_URL", "OLLAMA_TIMEOUT", "OLLAMA_REVIEW_MODEL", "OLLAMA_EMBED_MODEL",
                 "OLLAMA_FALLBACK_URL", "OPENROUTER_API_KEY", "OLLAMA_FALLBACK_REVIEW_MODEL",
                 "OLLAMA_FALLBACK_EMBED_MODEL", "OLLAMA_FALLBACK_EMBED_DIMENSIONS",
                 "OLLAMA_FALLBACK_TIMEOUT", "OLLAMA_PROBE_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fallback():
    server = FakeFallback()
    try:
        yield server
    finally:
        server.stop()


def test_review_and_embed_fall_back_when_primary_is_unreachable(fallback, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "1")
    monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "1")
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", fallback.url)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = OllamaClient()

    review = client.review_capture({"id": "x", "evidence": {"assistant": "done"}})
    embedded = client.embed(["a", "b"])

    assert review == REVIEW
    assert isinstance(embedded, EmbeddingBatch) and embedded.source == "fallback" and len(embedded.vectors) == 2
    assert any(path.endswith("/chat/completions") for path in fallback.paths)
    assert any(path.endswith("/embeddings") for path in fallback.paths)
    assert set(fallback.auth) == {"Bearer test-key"}


def test_primary_is_preferred_when_probe_succeeds(fallback, monkeypatch):
    primary = FakePrimary()
    try:
        monkeypatch.setenv("OLLAMA_URL", primary.url)
        monkeypatch.setenv("OLLAMA_TIMEOUT", "2")
        monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "1")
        monkeypatch.setenv("OLLAMA_FALLBACK_URL", fallback.url)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        client = OllamaClient()

        assert client.review_capture({"id": "x"}) == REVIEW
        assert client.embed(["a"]).source == "primary"
        assert fallback.paths == []
    finally:
        primary.stop()


def test_validation_failure_does_not_trigger_fallback(fallback, monkeypatch):
    primary = FakePrimary(generate_response="not json")
    try:
        monkeypatch.setenv("OLLAMA_URL", primary.url)
        monkeypatch.setenv("OLLAMA_TIMEOUT", "2")
        monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "1")
        monkeypatch.setenv("OLLAMA_FALLBACK_URL", fallback.url)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        result = OllamaClient().review_capture({"id": "x"})

        assert isinstance(result, DegradedStatus)
        assert fallback.paths == []
    finally:
        primary.stop()


def test_worker_drains_offline_capture_through_fallback(fallback, tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": "http://127.0.0.1:1", "OLLAMA_TIMEOUT": "1", "OLLAMA_PROBE_TIMEOUT": "1",
           "OLLAMA_FALLBACK_URL": fallback.url, "OPENROUTER_API_KEY": "test-key"}
    capture = {"id": "offline-1", "client": "opencode", "version": 1, "event": "completed_work",
               "source_session": "synthetic", "project": "fixture",
               "evidence": {"assistant": "Completed the migration; all tests pass."}}

    def run(*args, input=None):
        completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args],
                                   env={**os.environ, **env}, input=input, text=True,
                                   capture_output=True, timeout=20)
        payload = json.loads(completed.stdout)
        assert completed.returncode == 0, completed.stderr
        assert payload["ok"], payload
        return payload["result"]

    run("enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(capture))
    report = run("worker", "--drain")

    assert report["accepted"] == ["offline-1"]
    assert report["outbox"] == {"ready": 0, "running": 0, "done": 1}
    assert any(path.endswith("/chat/completions") for path in fallback.paths)
    assert any(path.endswith("/embeddings") for path in fallback.paths)
    listed = run("list")
    assert [record["content"] for record in listed["memories"]] == ["Completed migration; tests pass."]
    found = run("search", "--query", "migration tests")
    assert found["semantic_status"] == "available"
    assert [record["content"] for record in found["memories"]] == ["Completed migration; tests pass."]


def test_worker_survives_idempotency_conflict_on_replayed_capture(fallback, tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": "http://127.0.0.1:1", "OLLAMA_TIMEOUT": "1", "OLLAMA_PROBE_TIMEOUT": "1",
           "OLLAMA_FALLBACK_URL": fallback.url, "OPENROUTER_API_KEY": "test-key"}
    capture = {"id": "replay-1", "client": "opencode", "version": 1, "event": "completed_work",
               "source_session": "synthetic", "project": "fixture",
               "evidence": {"assistant": "Completed the migration; all tests pass."}}

    def run(*args, input=None):
        completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args],
                                   env={**os.environ, **env}, input=input, text=True,
                                   capture_output=True, timeout=20)
        payload = json.loads(completed.stdout)
        assert completed.returncode == 0, completed.stderr
        assert payload["ok"], payload
        return payload["result"]

    run("enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(capture))
    assert run("worker", "--drain")["accepted"] == ["replay-1"]

    fallback.review = {**REVIEW, "content": "A different reviewed statement."}
    run("enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(capture))
    report = run("worker", "--drain")

    assert report["rejected_by_reason"] == ["idempotency_conflict"]
    assert report["retrying"] == 0
    assert report["outbox"] == {"ready": 0, "running": 0, "done": 2}
