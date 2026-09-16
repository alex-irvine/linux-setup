import json
import os
import subprocess
import sys


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
    assert report["retrying"] == 1
    assert run(env, "status")["result"]["outbox"]["ready"] == 1


def test_concurrent_workers_claim_each_envelope_once(tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    for number in range(4):
        run(env, "enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps({"id": str(number), "content": "Task status: in progress"}))
    workers = [subprocess.Popen([sys.executable, "-m", "agent_memory.cli", "worker", "--drain"], env={**os.environ, **env}, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=10)
        assert worker.returncode == 0, stderr or stdout
    counts = run(env, "status")["result"]["outbox"]
    assert counts == {"ready": 0, "running": 0, "done": 4}


def test_worker_limit_processes_a_bounded_batch(tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}
    for number in range(7):
        run(env, "enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps({"id": str(number), "content": "Task status: in progress"}))

    report = run(env, "worker", "--limit", "3")["result"]

    assert report["outbox"] == {"ready": 4, "running": 0, "done": 3}
