import json
import os
import subprocess
import sys
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def run(env, *args, input=None, check=True):
    completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args], env={**os.environ, **env},
                               input=input, text=True, capture_output=True, timeout=10)
    payload = json.loads(completed.stdout)
    if check:
        assert completed.returncode == 0, completed.stderr
        assert payload["ok"], payload
    return payload


def test_capture_rejects_raw_events_when_the_local_reviewer_is_unavailable(tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": "http://127.0.0.1:1", "OLLAMA_TIMEOUT": "0.01"}
    candidates = [{"id": "completed", "client": "claude", "version": 1, "event": "completed_work", "source_session": "synthetic", "project": "fixture", "evidence": {"assistant": "Public completed work."}}]
    for candidate in candidates:
        run(env, "enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(candidate))
    ready = sorted((tmp_path / "state" / "outbox" / "ready").glob("*.json"))
    ready[0].replace(tmp_path / "state" / "outbox" / "running" / ready[0].name)

    # A restarted worker must recover the interrupted envelope before processing.
    report = run(env, "worker", "--drain")["result"]
    assert report["accepted"] == []
    # An unreachable reviewer is not the capture's fault: it waits without
    # spending one of its attempts.
    assert report["retrying"] == 0
    assert "unreachable" in report["provider_unavailable"]
    assert run(env, "status")["result"]["outbox"]["ready"] == 1
    waiting = next((tmp_path / "state" / "outbox" / "ready").glob("*.json"))
    assert json.loads(waiting.read_text())["attempts"] == 0


def test_concurrent_workers_claim_each_envelope_once(tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    for number in range(4):
        run(env, "enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps({"id": str(number), "content": "Task status: in progress"}))
    workers = [subprocess.Popen([sys.executable, "-m", "agent_memory.cli", "worker", "--drain"], env={**os.environ, **env}, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=10)
        assert worker.returncode == 0, stderr or stdout
    counts = run(env, "status")["result"]["outbox"]
    assert counts == {"ready": 0, "running": 0, "done": 4, "failed": 0}


def test_worker_limit_processes_a_bounded_batch(tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    for number in range(7):
        run(env, "enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps({"id": str(number), "content": "Task status: in progress"}))

    report = run(env, "worker", "--limit", "3")["result"]

    assert report["outbox"] == {"ready": 4, "running": 0, "done": 3, "failed": 0}


def test_completed_work_from_all_clients_is_saved_and_recovered_without_duplicates(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/embed":
                result = {"embeddings": [list(hashlib.sha256(text.encode()).digest()) for text in body["input"]]}
            elif "Decide the factual relation" in body["prompt"]:
                result = {"response": json.dumps({"relation": "distinct"})}
            else:
                event = json.loads(body["prompt"][body["prompt"].index("{"):])
                result = {"response": json.dumps({
                    "type": "convention", "scope": "project", "project": "fixture",
                    "content": event["evidence"]["assistant"], "importance": 0.8,
                    "confidence": 0.9, "tags": [], "durability": True, "supersedes": [],
                })}
            encoded = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": f"http://127.0.0.1:{server.server_port}"}
    try:
        clients = ("claude", "opencode", "codex", "hermes")
        contents = []
        for client in clients:
            for number in range(2):
                content = f"Use {client} report convention {number} for exported dates."
                contents.append(content)
                event = {"version": 1, "event": "completed_work", "client": client,
                         "source_session": f"fixture-{client}", "project": "fixture",
                         "evidence": {"assistant": content, "files": []}}
                run(env, "enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(event))

        report = run(env, "worker", "--drain")["result"]
        assert report["rejected_by_reason"] == []
        assert len(report["accepted"]) == 8
        records = run(env, "list", "--project", "fixture")["result"]["memories"]
        assert {record["content"] for record in records} == set(contents)
        assert {record["source_client"] for record in records} == set(clients)

        # Recover the same persisted jobs after an interruption; no second notes are created.
        done = tmp_path / "state" / "outbox" / "done"
        for path in done.glob("*.json"):
            path.replace(tmp_path / "state" / "outbox" / "ready" / path.name)
        replay = run(env, "worker", "--drain")["result"]
        assert replay["accepted"] == []
        assert replay["rejected_by_reason"] == ["duplicate"] * 8
        assert len(run(env, "list", "--project", "fixture")["result"]["memories"]) == 8
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
