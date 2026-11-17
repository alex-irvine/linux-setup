import json
import os
import subprocess
import sys
import time

import pytest

from agent_memory.capture import backlog_message


CAPTURE = {"id": "waiting-1", "client": "opencode", "version": 1, "event": "completed_work",
           "source_session": "synthetic", "project": "fixture",
           "evidence": {"assistant": "Completed the migration; all tests pass."}}
DAY = 24 * 3600


@pytest.fixture
def worker(tmp_path):
    """A worker whose Ollama server never answers, with notify-send replaced by a recorder."""
    bin_dir, sent = tmp_path / "bin", tmp_path / "notifications"
    bin_dir.mkdir()
    fake = bin_dir / "notify-send"
    fake.write_text(f'#!/bin/sh\nprintf "%s|" "$@" >> "{sent}"\necho >> "{sent}"\n')
    fake.chmod(0o755)
    env = {**os.environ, "AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
           "OLLAMA_URL": "http://127.0.0.1:1", "OLLAMA_TIMEOUT": "1", "OLLAMA_PROBE_TIMEOUT": "1",
           "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def run(*args, input=None):
        completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args], env=env, input=input,
                                   text=True, capture_output=True, timeout=20)
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["ok"], payload
        return payload["result"]

    def notifications():
        return sent.read_text().splitlines() if sent.exists() else []

    state = tmp_path / "state" / "backlog.json"
    return run, notifications, state


def set_state(path, **values):
    path.write_text(json.dumps({**json.loads(path.read_text()), **values}))


def test_backlog_alerts_once_after_a_day_of_waiting(worker):
    run, notifications, state = worker
    run("enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(CAPTURE))
    assert run("worker", "--drain")["backlog_alert"] is None

    # Ten minutes before the limit, with the last run ten minutes ago.
    set_state(state, waiting_seconds=DAY - 600, last_run=time.time() - 600)
    report = run("worker", "--drain")

    assert report["backlog_alert"].startswith("1 memory jobs are waiting; the queue has not emptied in 24 hours")
    assert "No answer from the Ollama server at http://127.0.0.1:1 has been recorded." in report["backlog_alert"]
    assert "Last run: Ollama at http://127.0.0.1:1 unreachable" in report["backlog_alert"]
    assert len(notifications()) == 1
    assert notifications()[0].startswith("--app-name=agent-memory|Memory backlog is not clearing|1 memory jobs")

    # The next run, still behind, does not repeat it.
    assert run("worker", "--drain")["backlog_alert"] is None
    assert len(notifications()) == 1


def test_time_asleep_does_not_count_as_waiting(worker):
    run, notifications, state = worker
    run("enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(CAPTURE))
    run("worker", "--drain")

    # The laptop was shut for three days; only fifteen minutes count.
    set_state(state, waiting_seconds=DAY - 3600, last_run=time.time() - 3 * DAY)
    report = run("worker", "--drain")

    assert report["backlog_alert"] is None
    assert DAY - 3600 + 900 <= json.loads(state.read_text())["waiting_seconds"] < DAY - 3600 + 905
    assert notifications() == []


def test_an_empty_queue_resets_the_count(worker, tmp_path):
    run, notifications, state = worker
    run("enqueue", "--kind", "capture", "--json-input", "-", input=json.dumps(CAPTURE))
    run("worker", "--drain")
    set_state(state, waiting_seconds=DAY - 600, last_run=time.time() - 600)
    for path in (tmp_path / "state" / "outbox" / "ready").glob("*.json"):
        path.unlink()

    report = run("worker", "--drain")

    assert report["backlog_alert"] is None
    assert json.loads(state.read_text())["waiting_seconds"] == 0
    assert notifications() == []


def test_alert_names_when_the_server_last_answered():
    answered = time.mktime((2026, 11, 14, 17, 5, 0, 0, 0, -1))
    message = backlog_message(412, {"waiting_seconds": 30 * 3600, "server_answered_at": answered},
                              {"provider_unavailable": "the CPU is 20% idle, below 50%"}, "http://server:11434")

    assert message == ("412 memory jobs are waiting; the queue has not emptied in 30 hours of laptop time. "
                       "The Ollama server at http://server:11434 last answered on Sat 14 Nov at 17:05. "
                       "Last run: the CPU is 20% idle, below 50%.")


def test_worker_records_when_the_server_answers(tmp_path):
    from test_ollama_fallback import FakePrimary

    primary = FakePrimary()
    try:
        env = {**os.environ, "AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault"),
               "OLLAMA_URL": primary.url, "OLLAMA_TIMEOUT": "2", "OLLAMA_PROBE_TIMEOUT": "1"}
        for args, stdin in ((("enqueue", "--kind", "capture", "--json-input", "-"), json.dumps(CAPTURE)),
                            (("worker", "--drain"), None)):
            subprocess.run([sys.executable, "-m", "agent_memory.cli", *args], env=env, input=stdin,
                           text=True, capture_output=True, timeout=20, check=True)
        state = json.loads((tmp_path / "state" / "backlog.json").read_text())
        assert time.time() - state["server_answered_at"] < 30
        assert state["waiting_seconds"] == 0
    finally:
        primary.stop()
