from __future__ import annotations

import json

from .model import MemoryRecord, normalize_content


KEYS = ("id", "type", "scope", "project", "importance", "confidence", "pinned", "status", "tags", "revision", "content_hash", "created_at", "updated_at")


def dump(record: MemoryRecord) -> str:
    values = record.to_dict()
    lines = ["---"]
    for key in KEYS:
        lines.append(f"{key}: {json.dumps(values[key], ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n---\n\n" + normalize_content(record.content) + "\n"


def load(text: str) -> dict:
    if not text.startswith("---\n"):
        raise ValueError("invalid memory frontmatter")
    header, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise ValueError("invalid memory frontmatter")
    values = {}
    for line in header.splitlines():
        key, value = line.split(": ", 1)
        values[key] = json.loads(value)
    values["content"] = normalize_content(body)
    return values
