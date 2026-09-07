from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Sequence
from uuid import UUID


class MemoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def uuid7() -> UUID:
    milliseconds = int(time.time() * 1000)
    value = (milliseconds << 80) | (0x7 << 76) | (secrets.randbits(12) << 64)
    value |= (0b10 << 62) | secrets.randbits(62)
    return UUID(int=value)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def normalize_content(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n").strip()


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def request_hash(operation: str, values: dict) -> str:
    payload = json.dumps({"operation": operation, **values}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AddRequest:
    request_id: str
    type: str
    scope: str
    content: str
    project: str | None = None
    importance: float = 0.5
    confidence: float = 1.0
    pinned: bool = False
    tags: Sequence[str] = ()


@dataclass(frozen=True)
class UpdateRequest:
    memory_id: UUID
    expected_revision: int
    expected_content_hash: str
    request_id: str
    content: str | None = None
    importance: float | None = None
    confidence: float | None = None
    pinned: bool | None = None
    tags: Sequence[str] | None = None


@dataclass(frozen=True)
class DeleteRequest:
    memory_id: UUID
    expected_revision: int
    expected_content_hash: str
    request_id: str


@dataclass(frozen=True)
class ListQuery:
    project: str | None = None
    scope: str | None = None
    type: str | None = None


@dataclass(frozen=True)
class SearchQuery:
    query: str
    project: str | None = None


@dataclass(frozen=True)
class MemoryRecord:
    id: UUID
    type: str
    scope: str
    project: str | None
    content: str
    importance: float
    confidence: float
    pinned: bool
    tags: tuple[str, ...]
    revision: int
    content_hash: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        value = asdict(self)
        value["id"] = str(self.id)
        value["tags"] = list(self.tags)
        return value


@dataclass(frozen=True)
class SearchResult:
    memories: list[MemoryRecord]

    def to_dict(self) -> dict:
        return {"memories": [memory.to_dict() for memory in self.memories]}


@dataclass(frozen=True)
class DeleteResult:
    id: UUID
    revision: int
    content_hash: str

    def to_dict(self) -> dict:
        return {"id": str(self.id), "revision": self.revision, "content_hash": self.content_hash}
