import hashlib
import json
import multiprocessing
from contextlib import contextmanager
from pathlib import Path

from agent_memory.index import MemoryIndex
from agent_memory.migration import MigrationService
from agent_memory.store import MarkdownStore, MemoryService


class ObservedMigration(MigrationService):
    def __init__(self, *args, held, release, entered, hold=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.held, self.release, self.entered, self.hold = held, release, entered, hold

    @contextmanager
    def _locked(self, batch):
        with super()._locked(batch):
            self.entered.set()
            if self.hold:
                self.held.set()
                assert self.release.wait(10)
            yield


def import_while_observing(root, held, release, entered, hold):
    root = Path(root)
    service = MemoryService(MarkdownStore(root / "vault", root / "state"), MemoryIndex(root / "state" / "memory.sqlite3"))
    ObservedMigration(service, root / "state", root / "archive", root / "hermes", root / "claude", root / "project_map.json",
                      held=held, release=release, entered=entered, hold=hold).import_local("locked")


def test_same_batch_lock_blocks_second_process_and_preserves_immutable_snapshot(tmp_path):
    archive, hermes, claude = tmp_path / "archive", tmp_path / "hermes", tmp_path / "claude"
    archive.mkdir(); hermes.mkdir(); claude.mkdir()
    for number in range(2):
        (archive / f"fixture-{number}.md").write_text(f"Synthetic migration fixture {number}.", encoding="utf-8")
    (tmp_path / "project_map.json").write_text("{}", encoding="utf-8")
    service = MemoryService(MarkdownStore(tmp_path / "vault", tmp_path / "state"), MemoryIndex(tmp_path / "state" / "memory.sqlite3"))
    migration = MigrationService(service, tmp_path / "state", archive, hermes, claude, tmp_path / "project_map.json")
    migration.snapshot("locked")
    manifest_path = tmp_path / "state" / "snapshots" / "locked" / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    raw_bytes = {path.name: path.read_bytes() for path in (manifest_path.parent / "raw").glob("*")}
    context = multiprocessing.get_context("fork")
    held, release, first_entered, second_entered = (context.Event() for _ in range(4))
    first = context.Process(target=import_while_observing, args=(str(tmp_path), held, release, first_entered, True))
    second = context.Process(target=import_while_observing, args=(str(tmp_path), held, release, second_entered, False))
    first.start(); assert held.wait(10)
    second.start()
    assert not second_entered.wait(0.5)
    release.set()
    first.join(10); second.join(10)
    assert first.exitcode == 0 and second.exitcode == 0
    assert manifest_path.read_bytes() == manifest_bytes
    assert {path.name: path.read_bytes() for path in (manifest_path.parent / "raw").glob("*")} == raw_bytes
    rows = migration._rows("locked")
    assert len(rows) == 2 and len({row["source_identity"] for row in rows}) == 2
    assert all(len(row["imported_ids"]) == 1 for row in rows)
    assert migration.report("locked")["unaccounted_sources"] == 0
    assert migration.verify("locked")["verified"] is True
