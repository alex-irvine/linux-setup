#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from migrate_memory_to_mem0 import discover_files, build_payloads  # noqa: E402


def test_discover_files_finds_archive_and_hermes(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "a.md").write_text("note a")
    (memory_dir / "b.md").write_text("note b")
    hermes_dir = tmp_path / "hermes_memories"
    hermes_dir.mkdir()
    (hermes_dir / "MEMORY.md").write_text("hermes memory")
    (hermes_dir / "USER.md").write_text("hermes user")

    files = discover_files(memory_dir=memory_dir, hermes_dir=hermes_dir)

    assert len(files) == 4
    assert {f.path.name for f in files} == {"a.md", "b.md", "MEMORY.md", "USER.md"}
    sources = {f.path.name: f.source for f in files}
    assert sources["a.md"] == "dotfiles-archive"
    assert sources["MEMORY.md"] == "hermes"


def test_discover_files_skips_missing_hermes_dir(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "a.md").write_text("note a")

    files = discover_files(memory_dir=memory_dir, hermes_dir=tmp_path / "nonexistent")

    assert len(files) == 1
    assert files[0].path.name == "a.md"


def test_build_payloads_shapes_mem0_add_call(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "note.md").write_text("Prefers Go over Python")

    files = discover_files(memory_dir=memory_dir, hermes_dir=tmp_path / "nonexistent")
    payloads = list(build_payloads(files))

    assert len(payloads) == 1
    p = payloads[0]
    assert p["messages"] == [{"role": "user", "content": "Prefers Go over Python"}]
    assert p["user_id"] == "alex"
    assert p["metadata"]["source"] == "dotfiles-archive"
    assert p["metadata"]["original_file"] == "note.md"


def test_build_payloads_skips_empty_files(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "empty.md").write_text("   \n  ")

    files = discover_files(memory_dir=memory_dir, hermes_dir=tmp_path / "nonexistent")
    payloads = list(build_payloads(files))

    assert payloads == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
