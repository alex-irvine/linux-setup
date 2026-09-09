import hashlib
import json
import multiprocessing
from pathlib import Path
from uuid import UUID

from agent_memory.migration import MigrationService
from agent_memory.model import MemoryError
from agent_memory.store import MarkdownStore, MemoryService
from agent_memory.index import MemoryIndex


def _concurrent_import(root: str) -> None:
    root_path = Path(root)
    service = MemoryService(MarkdownStore(root_path / "vault", root_path / "state"), MemoryIndex(root_path / "state" / "memory.sqlite3"))
    MigrationService(service, root_path / "state", root_path / "archive", root_path / "hermes", root_path / "claude", root_path / "project_map.json").import_local("concurrent")


def test_migration_is_resumable_and_accounts_for_every_source(tmp_path):
    source = tmp_path / "sources"
    archive = source / "archive"
    hermes = source / "hermes"
    claude = source / "claude"
    archive.mkdir(parents=True)
    hermes.mkdir()
    (claude / "project" / "memory").mkdir(parents=True)
    for number in range(15):
        content = "Duplicate fact" if number == 1 else "Feature flag is enabled" if number == 2 else f"Archived fact {number}"
        (archive / f"archive-{number}.md").write_text(content, encoding="utf-8")
    (hermes / "MEMORY.md").write_text("Duplicate fact", encoding="utf-8")
    (hermes / "USER.md").write_text("Feature flag is disabled", encoding="utf-8")
    (claude / "project" / "memory" / "MEMORY.md").write_text("Claude project fact", encoding="utf-8")
    project_map = source / "project_map.json"
    project_map.write_text(json.dumps({str(claude / "project"): "app-one", "/other": "app-two"}), encoding="utf-8")
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"),
                            MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, project_map)

    batch = "synthetic"
    assert migration.snapshot(batch)["source_files"] == 18
    interrupted = migration.import_local(batch, stop_after=7)
    assert interrupted["interrupted"] is True
    resumed = migration.import_local(batch)
    assert resumed["processed"] == 11
    assert resumed["imported"] == 10
    pages = [
        {"app_id": "app-one", "cursor": "cursor-one", "records": [{"id": "one", "memory": "Hosted fact"}]},
        {"app_id": "app-two", "cursor": "cursor-two", "records": [{"id": "two", "memory": "Later hosted fact"}]},
    ]
    hosted = migration.import_mem0(batch, pages=pages, quota_failure_after_page=1)
    assert hosted["deferred"]["next_action"] == "manual platform export or support-assisted raw export"
    assert hosted["resume_cursor"] == "cursor-one"
    resumed_hosted = migration.import_mem0(batch, pages=pages)
    assert resumed_hosted["imported"] == 1
    assert resumed_hosted["deferred"]["reason"] == "quota_exhausted"
    assert resumed_hosted["resume_cursor"] == "cursor-two"
    rows_before_mismatch = len(migration._rows(batch))
    try:
        migration.import_mem0(batch, pages=pages, complete_counts={"app-one": 1, "app-two": 2})
    except MemoryError as error:
        assert error.code == "verification_failed"
    else:
        raise AssertionError("mismatched multi-scope completion was accepted")
    assert len(migration._rows(batch)) == rows_before_mismatch
    assert not any(row.get("completion") for row in migration._rows(batch))
    completed_hosted = migration.import_mem0(batch, pages=pages, complete_counts={"app-two": 1})
    assert completed_hosted["deferred"] is None
    rows_before_rerun = len(migration._rows(batch))
    assert migration.import_mem0(batch, pages=pages)["imported"] == 0
    assert len(migration._rows(batch)) == rows_before_rerun
    hosted_rows = [row for row in migration._rows(batch) if row["source_kind"] == "hosted"]
    assert {row["source_identity"] for row in hosted_rows if row["imported_ids"]} == {"alex/app-one/one", "alex/app-two/two"}
    report = migration.report(batch)
    assert report["source_files"] == 18
    assert report["unaccounted_sources"] == 0
    assert report["deferred_hosted_scopes"] == []
    assert report["contradictions"] == 1
    assert migration.import_local(batch)["imported"] == 0
    assert migration.verify(batch)["verified"] is True
    report_text = (tmp_path / "vault" / "Migration" / "report.md").read_text(encoding="utf-8")
    for field in ("Source identity", "Source hash", "Raw snapshot", "Raw count", "Cursor",
                  "Imported IDs", "Duplicate IDs", "Conflict links", "Failures", "Deferrals",
                  "Waiver decision"):
        assert field in report_text
    assert str(archive / "archive-0.md") in report_text
    excluded = next(row for row in migration._rows(batch) if row["source_identity"] == str(archive / "archive-0.md"))
    migration.disposition(batch, str(archive / "archive-0.md"), "defer", "user_excluded_transient",
                          "user_approved", excluded["imported_ids"][0])
    migration.disposition(batch, str(archive / "archive-3.md"), "waive", "transient", "user_approved")
    resumed_report = migration.report(batch)
    assert resumed_report["local_deferrals"] == 1
    assert resumed_report["waivers"] == 1
    assert not (tmp_path / "vault" / "notes" / f"{excluded['imported_ids'][0]}.md").exists()
    assert migration.verify(batch)["verified"] is True
    manifest = json.loads((tmp_path / "state" / "snapshots" / batch / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["sources"]:
        snapshot = tmp_path / "state" / "snapshots" / batch / entry["raw_snapshot"]
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == entry["source_hash"]


def test_migration_same_batch_processes_serialize_without_duplicate_imports(tmp_path):
    archive, hermes, claude = tmp_path / "archive", tmp_path / "hermes", tmp_path / "claude"
    archive.mkdir(); hermes.mkdir(); claude.mkdir()
    for number in range(3):
        (archive / f"fixture-{number}.md").write_text(f"Synthetic migration fixture {number}.", encoding="utf-8")
    (tmp_path / "project_map.json").write_text("{}", encoding="utf-8")
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"), MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, tmp_path / "project_map.json")
    assert migration.snapshot("concurrent")["snapshot"] == "created"
    processes = [multiprocessing.get_context("fork").Process(target=_concurrent_import, args=(str(tmp_path),)) for _ in range(2)]
    for process in processes: process.start()
    for process in processes: process.join(10); assert process.exitcode == 0
    rows = migration._rows("concurrent")
    assert len(rows) == 3
    assert len({row["source_identity"] for row in rows}) == 3
    assert all(len(row["imported_ids"]) == 1 for row in rows)
    assert migration.verify("concurrent")["verified"] is True
    assert migration.report("concurrent")["unaccounted_sources"] == 0


def test_hosted_deferral_requires_matching_explicit_complete_count(tmp_path):
    project_map = tmp_path / "project_map.json"
    project_map.write_text(json.dumps({"/project": "app-two"}), encoding="utf-8")
    archive, hermes, claude = tmp_path / "archive", tmp_path / "hermes", tmp_path / "claude"
    archive.mkdir(); hermes.mkdir(); claude.mkdir()
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"),
                            MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, project_map)
    migration.snapshot("manual")
    migration.import_mem0("manual")
    page = {"app_id": "app-two", "cursor": "manual-export", "records": [
        {"id": "one", "memory": "Synthetic hosted fact"},
    ]}

    rows_before_mismatch = len(migration._rows("manual"))
    try:
        migration.import_mem0("manual", pages=[page], complete_counts={"app-two": 2})
    except MemoryError as error:
        assert error.code == "verification_failed"
    else:
        raise AssertionError("mismatched hosted export count was accepted")
    assert len(migration._rows("manual")) == rows_before_mismatch
    assert not (tmp_path / "state" / "snapshots" / "manual" / "hosted").exists()
    imported = migration.import_mem0("manual", pages=[page])
    assert imported["deferred"]["reason"] == "quota_exhausted"
    assert migration.report("manual")["deferred_hosted_scopes"] == ["alex/app-two"]
    assert migration.import_mem0("manual", pages=[page], complete_counts={"app-two": 1})["deferred"] is None
    assert migration.report("manual")["deferred_hosted_scopes"] == []


def test_empty_hosted_import_accounts_for_every_mapped_app_and_corrects_legacy_fixture(tmp_path):
    project_map = tmp_path / "project_map.json"
    project_map.write_text(json.dumps({"/one": "real-one", "/two": "real-two"}), encoding="utf-8")
    archive, hermes, claude = tmp_path / "archive", tmp_path / "hermes", tmp_path / "claude"
    archive.mkdir(); hermes.mkdir(); claude.mkdir()
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"),
                            MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, project_map)
    migration.snapshot("inventory")
    legacy_entry = {"source_kind": "hosted", "source_identity": "alex/app-two",
                    "source_hash": None, "raw_snapshot": None}
    migration._append("inventory", migration._row(legacy_entry, hosted_scope=True, deferred={"reason": "quota_exhausted"}))

    result = migration.import_mem0("inventory")
    assert result["deferred_scopes"] == ["alex/real-one", "alex/real-two"]
    summary = migration.report("inventory")
    assert summary["deferred_hosted_scopes"] == ["alex/real-one", "alex/real-two"]
    latest = migration._hosted_scope_latest(migration._rows("inventory"))
    assert latest["alex/app-two"]["correction"] == "invalid synthetic fixture scope"


def test_hosted_completion_can_account_for_user_approved_missing_records(tmp_path):
    project_map = tmp_path / "project_map.json"
    project_map.write_text(json.dumps({"/project": "real-app"}), encoding="utf-8")
    archive, hermes, claude = tmp_path / "archive", tmp_path / "hermes", tmp_path / "claude"
    archive.mkdir(); hermes.mkdir(); claude.mkdir()
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"),
                            MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, project_map)
    migration.snapshot("waiver")
    migration.import_mem0("waiver")
    page = {"app_id": "real-app", "cursor": "saved-page", "records": [
        {"id": "one", "memory": "Synthetic hosted fact"},
    ]}

    result = migration.import_mem0("waiver", pages=[page], complete_counts={"real-app": 2},
                                   waived_missing={"real-app": 1})
    assert result["deferred"] is None
    scope = migration._hosted_scope_latest(migration._rows("waiver"))["alex/real-app"]
    assert scope["completion"] == {"expected_count": 2, "verified_count": 1, "waived_missing": 1}
    assert scope["waiver"] == {"status": "waived", "reason": "missing_hosted_records",
                               "decision": "user_approved"}


def test_structured_hosted_export_is_labeled_as_transformed(tmp_path):
    project_map = tmp_path / "project_map.json"
    project_map.write_text(json.dumps({"/project": "real-app"}), encoding="utf-8")
    archive, hermes, claude = tmp_path / "archive", tmp_path / "hermes", tmp_path / "claude"
    archive.mkdir(); hermes.mkdir(); claude.mkdir()
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"),
                            MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, project_map)
    migration.snapshot("transformed")
    page = {"app_id": "real-app", "cursor": "structured-export", "records": [
        {"id": "export-0", "memory": "Synthetic transformed fact", "_transformed": True},
    ]}

    migration.import_mem0("transformed", pages=[page], complete_counts={"real-app": 1})
    row = next(row for row in migration._rows("transformed") if row.get("imported_ids"))
    assert row["transformed"] is True
    record = service.get(UUID(row["imported_ids"][0]))
    assert "hosted-transformed" in record.tags
