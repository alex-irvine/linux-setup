#!/usr/bin/env python3
"""One-time (re-runnable) import of pre-Mem0 notes into Mem0 Platform.

Reads:
  - every *.md file in the archived cross-provider notes under ~/dotfiles
  - ~/.hermes/memories/MEMORY.md and USER.md (Hermes's built-in files, copied
    not moved -- the live files keep running additively alongside the mem0
    provider by Hermes's own design; see the implementation plan Task 9)

For each file, calls MemoryClient.add() once with the file's full text,
tagged with metadata identifying its origin. Mem0's own extraction pipeline
pulls the distinct facts out of the text -- this script does not pre-split
facts itself.

Usage:
  python3 migrate_memory_to_mem0.py --dry-run          # print what would be sent
  MEM0_API_KEY=m0-... python3 migrate_memory_to_mem0.py  # actually import
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

DOTFILES_MEMORY_DIR = (
    Path.home() / "dotfiles" / "docs" / "cross-provider-memory" / "archive-2026-07-22"
)
HERMES_MEMORIES_DIR = Path.home() / ".hermes" / "memories"
DEFAULT_USER_ID = "alex"
DEFAULT_AGENT_ID = "migration"


class MemoryFile(NamedTuple):
    path: Path
    source: str  # "dotfiles-archive" or "hermes"


def discover_files(memory_dir: Path = DOTFILES_MEMORY_DIR,
                    hermes_dir: Path = HERMES_MEMORIES_DIR) -> list[MemoryFile]:
    files: list[MemoryFile] = []
    if memory_dir.is_dir():
        for p in sorted(memory_dir.glob("*.md")):
            files.append(MemoryFile(p, "dotfiles-archive"))
    for name in ("MEMORY.md", "USER.md"):
        p = hermes_dir / name
        if p.is_file():
            files.append(MemoryFile(p, "hermes"))
    return files


def build_payloads(files: list[MemoryFile]) -> Iterator[dict]:
    for f in files:
        text = f.path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        yield {
            "messages": [{"role": "user", "content": text}],
            "user_id": DEFAULT_USER_ID,
            "agent_id": DEFAULT_AGENT_ID,
            "metadata": {
                "source": f.source,
                "original_file": f.path.name,
                "migration": "2026-07-22-cross-provider-memory",
            },
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="print payloads instead of calling Mem0")
    args = parser.parse_args(argv)

    files = discover_files()
    if not files:
        print("no memory files found", file=sys.stderr)
        return 1

    payloads = list(build_payloads(files))
    print(f"discovered {len(files)} files, {len(payloads)} non-empty payloads")

    if args.dry_run:
        for p in payloads:
            print(f"  would add: {p['metadata']['source']}/{p['metadata']['original_file']} "
                  f"({len(p['messages'][0]['content'])} chars) user_id={p['user_id']}")
        return 0

    api_key = os.environ.get("MEM0_API_KEY")
    if not api_key:
        print("MEM0_API_KEY not set in environment", file=sys.stderr)
        return 1

    from mem0 import MemoryClient  # imported here so --dry-run needs no install
    client = MemoryClient(api_key=api_key)
    for p in payloads:
        client.add(p["messages"], user_id=p["user_id"], agent_id=p["agent_id"],
                    metadata=p["metadata"])
        print(f"  imported: {p['metadata']['source']}/{p['metadata']['original_file']}")

    print(f"done: {len(payloads)} files imported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
