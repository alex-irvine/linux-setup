import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def memory_app(tmp_path):
    env = {"AGENT_MEMORY_HOME": str(tmp_path / "state"), "AGENT_MEMORY_VAULT": str(tmp_path / "vault")}

    def run(*args, check=True):
        completed = subprocess.run([sys.executable, "-m", "agent_memory.cli", *args], env={**os.environ, **env},
                                   text=True, capture_output=True, timeout=10)
        assert completed.stdout, completed.stderr
        result = json.loads(completed.stdout)
        if check:
            assert completed.returncode == 0, completed.stderr
            assert result["ok"]
            return result["result"]
        return result

    return run


def add(memory_app, request_id, content, scope="project", project="dotfiles"):
    command = ["add", "--request-id", request_id, "--type", "fact", "--scope", scope, "--content", content]
    if project:
        command.extend(["--project", project])
    return memory_app(*command)


def test_reconcile_invalid_notes_and_rebuild_deleted_catalog(memory_app, tmp_path):
    external = add(memory_app, "external", "Original body")
    invalid = add(memory_app, "invalid", "Will be corrupted")
    notes = tmp_path / "vault" / "notes"
    external_path = notes / f"{external['id']}.md"
    external_path.write_text(external_path.read_text(encoding="utf-8").replace("Original body", "Edited directly"), encoding="utf-8")
    invalid_path = notes / f"{invalid['id']}.md"
    invalid_path.write_text("not frontmatter", encoding="utf-8")
    reconciled = memory_app("reconcile")
    assert reconciled["external_edits"] == [external["id"]]
    assert reconciled["invalid_notes"][0]["path"] == str(invalid_path)
    assert str(invalid_path) in reconciled["excluded_paths"]
    current = memory_app("get", "--id", external["id"])
    assert current["content"] == "Edited directly"
    assert current["content_hash"] != external["content_hash"]
    sqlite_path = tmp_path / "state" / "memory.sqlite3"
    sqlite_path.unlink()
    rebuilt = memory_app("rebuild")
    assert rebuilt["active_count"] == 1
    assert rebuilt["invalid_notes"][0]["path"] == str(invalid_path)
    reopened = memory_app("search", "--query", "edited", "--project", "dotfiles")
    assert [memory["id"] for memory in reopened["memories"]] == [external["id"]]
    with sqlite3.connect(sqlite_path) as catalog:
        assert catalog.execute("SELECT id FROM memories").fetchall() == [(external["id"],)]
    status = memory_app("status")
    assert status["invalid_notes"][0]["path"] == str(invalid_path)


def test_concurrent_stale_writers_preserve_one_winner_and_conflicts(memory_app, tmp_path):
    current = add(memory_app, "initial", "Initial content")

    def update(number):
        return memory_app("update", "--id", current["id"], "--expected-revision", str(current["revision"]),
                          "--expected-content-hash", current["content_hash"], "--request-id", f"writer-{number}",
                          "--content", f"Writer {number}", check=False)

    with ThreadPoolExecutor(max_workers=4) as writers:
        outcomes = list(writers.map(update, range(4)))
    assert sum(outcome["ok"] for outcome in outcomes) == 1
    assert {outcome["error"]["code"] for outcome in outcomes if not outcome["ok"]} == {"revision_conflict"}
    assert "---\n" in (tmp_path / "vault" / "notes" / f"{current['id']}.md").read_text(encoding="utf-8")
    conflicts = list((tmp_path / "vault" / "Conflicts").glob("*.md"))
    assert len(conflicts) == 3
    assert all(path.read_text(encoding="utf-8").startswith("---\n") for path in conflicts)


def test_guarded_administration_requires_one_time_token_and_audit(memory_app, tmp_path):
    record = add(memory_app, "admin-memory", "Disposable")
    denied = memory_app("delete-all", "--request-id", "denied", "--token", "wrong", check=False)
    assert denied["error"]["code"] == "invalid_authorization"
    authorization = memory_app("admin", "authorize", "--action", "delete-all", "--ttl", "60")
    deleted = memory_app("delete-all", "--request-id", "delete-all", "--token", authorization["token"])
    assert deleted["count"] == 1
    assert deleted["affected_ids"] == [record["id"]]
    assert deleted["audit_record_id"]
    reused = memory_app("delete-all", "--request-id", "reused", "--token", authorization["token"], check=False)
    assert reused["error"]["code"] == "invalid_authorization"
    purge_auth = memory_app("admin", "authorize", "--action", "purge", "--ttl", "60")
    missing_confirmation = memory_app("purge", "--request-id", "purge-denied", "--token", purge_auth["token"],
                                     "--memory-id", record["id"], "--content-hash", record["content_hash"], check=False)
    assert missing_confirmation["error"]["code"] == "invalid_request"
    purged = memory_app("purge", "--request-id", "purge", "--token", purge_auth["token"], "--memory-id", record["id"],
                        "--content-hash", record["content_hash"], "--confirm-history-rewrite")
    assert purged["affected_ids"] == [record["id"]]
    audit = [json.loads(line) for line in (tmp_path / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [entry["action"] for entry in audit] == ["delete-all", "purge"]
