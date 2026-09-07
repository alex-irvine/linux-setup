import hashlib
import json

from agent_memory.migration import MigrationService
from agent_memory.store import MarkdownStore, MemoryService
from agent_memory.index import MemoryIndex


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
    assert hosted["deferred"]["next_action"] == "post-reset delta export"
    assert hosted["resume_cursor"] == "cursor-one"
    resumed_hosted = migration.import_mem0(batch, pages=pages)
    assert resumed_hosted["imported"] == 1
    assert resumed_hosted["resume_cursor"] == "cursor-two"
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
