import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_memory.ollama import DegradedStatus, EmbeddingBatch, OllamaClient


REVIEW = {"type": "lesson", "scope": "global", "project": None, "content": "Completed migration; tests pass.",
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
    """The local Ollama: same API and models as the primary."""

    def __init__(self, review=None, loaded=("qwen3:1.7b",)):
        self.review = review or REVIEW
        self.loaded = list(loaded)
        self.bodies = []
        super().__init__(BaseHTTPRequestHandler)

    def post(self, path, request):
        self.bodies.append(request)
        if path.endswith("/api/generate"):
            if '"relation"' in request.get("prompt", ""):
                return {"response": json.dumps({"relation": "distinct"})}
            return {"response": json.dumps(self.review)}
        if path.endswith("/api/embed"):
            return {"embeddings": [[0.5, 0.25] * 384 for _ in request.get("input", [])]}
        return {"error": "unexpected path"}

    def get(self, path):
        if path.endswith("/api/ps"):
            return {"models": [{"name": name} for name in self.loaded]}
        return {"models": []}


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
    for name in ("OLLAMA_URL", "OLLAMA_TIMEOUT", "OLLAMA_REVIEW_MODEL", "OLLAMA_EMBED_MODEL", "OLLAMA_PROBE_TIMEOUT",
                 "OLLAMA_FALLBACK_URL", "OLLAMA_FALLBACK_TIMEOUT", "OLLAMA_FALLBACK_LIMIT", "OLLAMA_FALLBACK_THREADS",
                 "OLLAMA_FALLBACK_MIN_CPU_IDLE", "OLLAMA_FALLBACK_MIN_MEMORY", "OLLAMA_FALLBACK_ON_BATTERY"):
        monkeypatch.delenv(name, raising=False)


def worker_env(fallback, tmp_path, **limits):
    """Environment for a worker whose server is down and whose local Ollama is the fake.

    The capacity limits default to zero so the tests do not depend on how
    busy the machine running them is, or whether it is on battery.
    """
    return {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
            "OLLAMA_URL": "http://127.0.0.1:1", "OLLAMA_TIMEOUT": "1", "OLLAMA_PROBE_TIMEOUT": "1",
            "OLLAMA_FALLBACK_URL": fallback.url, "OLLAMA_FALLBACK_MIN_CPU_IDLE": "0",
            "OLLAMA_FALLBACK_MIN_MEMORY": "0", "OLLAMA_FALLBACK_ON_BATTERY": "1", **limits}


def cli(env):
    def run(*args, input=None):
        completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args],
                                   env={**os.environ, **env}, input=input, text=True,
                                   capture_output=True, timeout=20)
        payload = json.loads(completed.stdout)
        assert completed.returncode == 0, completed.stderr
        assert payload["ok"], payload
        return payload["result"]
    return run


def capture(capture_id, evidence="Completed the migration; all tests pass."):
    return json.dumps({"id": capture_id, "client": "opencode", "version": 1, "event": "completed_work",
                       "source_session": "synthetic", "project": "fixture", "evidence": {"assistant": evidence}})


@pytest.fixture
def fallback():
    server = FakeFallback()
    try:
        yield server
    finally:
        server.stop()


def test_review_and_embed_fall_back_to_local_ollama_when_primary_is_unreachable(fallback, monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "1")
    monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "1")
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", fallback.url)
    monkeypatch.setenv("OLLAMA_FALLBACK_THREADS", "3")
    client = OllamaClient()

    review = client.review_capture({"id": "x", "evidence": {"assistant": "done"}})
    embedded = client.embed(["a", "b"])

    assert review == REVIEW
    assert isinstance(embedded, EmbeddingBatch) and embedded.source == "fallback" and len(embedded.vectors) == 2
    # Same models as the server, so cached vectors stay comparable.
    assert embedded.model == "nomic-embed-text"
    assert [body["model"] for body in fallback.bodies] == ["qwen3:1.7b", "nomic-embed-text"]
    for body in fallback.bodies:
        assert body["keep_alive"] == "1m"
        assert body["options"] == {"num_thread": 3, "num_ctx": 4096}


def test_primary_is_preferred_when_probe_succeeds(fallback, monkeypatch):
    primary = FakePrimary()
    try:
        monkeypatch.setenv("OLLAMA_URL", primary.url)
        monkeypatch.setenv("OLLAMA_TIMEOUT", "2")
        monkeypatch.setenv("OLLAMA_PROBE_TIMEOUT", "1")
        monkeypatch.setenv("OLLAMA_FALLBACK_URL", fallback.url)
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

        result = OllamaClient().review_capture({"id": "x"})

        assert isinstance(result, DegradedStatus)
        assert fallback.paths == []
    finally:
        primary.stop()


def test_worker_drains_offline_capture_through_local_ollama(fallback, tmp_path):
    run = cli(worker_env(fallback, tmp_path))

    run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("offline-1"))
    report = run("worker", "--drain")

    assert report["accepted"] == ["offline-1"]
    assert report["outbox"] == {"ready": 0, "running": 0, "done": 1, "failed": 0}
    assert any(path.endswith("/api/generate") for path in fallback.paths)
    assert any(path.endswith("/api/embed") for path in fallback.paths)
    listed = run("list")
    assert [record["content"] for record in listed["memories"]] == ["Completed migration; tests pass."]
    found = run("search", "--query", "migration tests")
    assert found["semantic_status"] == "available"
    assert [record["content"] for record in found["memories"]] == ["Completed migration; tests pass."]


def test_worker_survives_idempotency_conflict_on_replayed_capture(fallback, tmp_path):
    run = cli(worker_env(fallback, tmp_path))

    run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("replay-1"))
    assert run("worker", "--drain")["accepted"] == ["replay-1"]

    fallback.review = {**REVIEW, "content": "A different reviewed statement."}
    run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("replay-1"))
    report = run("worker", "--drain")

    assert report["rejected_by_reason"] == ["idempotency_conflict"]
    assert report["retrying"] == 0
    assert report["outbox"] == {"ready": 0, "running": 0, "done": 2, "failed": 0}


def waiting_attempts(tmp_path):
    return [json.loads(path.read_text())["attempts"] for path in (tmp_path / "state" / "outbox" / "ready").glob("*.json")]


def test_worker_leaves_captures_for_the_next_run_when_the_machine_is_busy(fallback, tmp_path):
    run = cli(worker_env(fallback, tmp_path, OLLAMA_FALLBACK_MIN_CPU_IDLE="101"))

    run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("busy-1"))
    report = run("worker", "--drain")

    assert report["accepted"] == []
    assert "the CPU is" in report["provider_unavailable"]
    assert report["outbox"] == {"ready": 1, "running": 0, "done": 0, "failed": 0}
    assert waiting_attempts(tmp_path) == [0]
    assert not any(path.endswith(("/api/generate", "/api/embed")) for path in fallback.paths)


def test_worker_leaves_captures_for_the_next_run_when_local_ollama_runs_another_model(tmp_path):
    fallback = FakeFallback(loaded=("qwen3:1.7b", "gpt-oss:20b"))
    try:
        run = cli(worker_env(fallback, tmp_path))

        run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("shared-1"))
        report = run("worker", "--drain")

        assert report["accepted"] == []
        assert "it is running gpt-oss:20b" in report["provider_unavailable"]
        assert waiting_attempts(tmp_path) == [0]
        assert not any(path.endswith(("/api/generate", "/api/embed")) for path in fallback.paths)
    finally:
        fallback.stop()


def test_worker_sends_local_ollama_at_most_its_limit_per_run(fallback, tmp_path):
    run = cli(worker_env(fallback, tmp_path, OLLAMA_FALLBACK_LIMIT="1"))
    run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("first", "Completed the first migration."))
    run("enqueue", "--kind", "capture", "--json-input", "-", input=capture("second", "Completed the second migration."))

    report = run("worker", "--drain")

    assert len(report["accepted"]) == 1
    assert "took its 1 captures for this run" in report["provider_unavailable"]
    assert report["outbox"] == {"ready": 1, "running": 0, "done": 1, "failed": 0}
    assert waiting_attempts(tmp_path) == [0]
