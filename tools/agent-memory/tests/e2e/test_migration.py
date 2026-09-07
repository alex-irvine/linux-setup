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
    project_map.write_text(json.dumps({str(claude / "project"): "demo"}), encoding="utf-8")
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
    hosted = migration.import_mem0(batch, pages=[
        [{"id": "one", "memory": "Hosted fact", "metadata": {"source": "export"}}],
        [{"id": "two", "memory": "Later hosted fact", "metadata": {"source": "export"}}],
    ], quota_failure_after_page=1)
    assert hosted["deferred"]["next_action"] == "post-reset delta export"
    report = migration.report(batch)
    assert report["source_files"] == 18
    assert report["unaccounted_sources"] == 0
    assert report["deferred_hosted_scopes"] == ["alex/app-two"]
    assert report["contradictions"] == 1
    assert migration.import_local(batch)["imported"] == 0
    assert migration.verify(batch)["verified"] is True
    manifest = json.loads((tmp_path / "state" / "snapshots" / batch / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["sources"]:
        snapshot = tmp_path / "state" / "snapshots" / batch / entry["raw_snapshot"]
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == entry["source_hash"]
