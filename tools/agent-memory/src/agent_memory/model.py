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


MEMORY_TYPES = frozenset({"preference", "correction", "fact", "convention", "decision", "lesson"})
MEMORY_SCOPES = frozenset({"global", "project"})
MEMORY_STATUSES = frozenset({"active", "superseded", "deleted"})


def validate_domain(name: str, value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        raise MemoryError(f"invalid_{name}", f"unsupported memory {name}: {value}")


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

    def __post_init__(self) -> None:
        validate_domain("type", self.type, MEMORY_TYPES)
        validate_domain("scope", self.scope, MEMORY_SCOPES)


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
    status: str | None = None

    def __post_init__(self) -> None:
        if self.status is not None:
            validate_domain("status", self.status, MEMORY_STATUSES)


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
    status: str | None = "active"

    def __post_init__(self) -> None:
        if self.type is not None:
            validate_domain("type", self.type, MEMORY_TYPES)
        if self.scope is not None:
            validate_domain("scope", self.scope, MEMORY_SCOPES)
        if self.status is not None:
            validate_domain("status", self.status, MEMORY_STATUSES)


@dataclass(frozen=True)
class SearchQuery:
    query: str
    project: str | None = None
    status: str | None = "active"

    def __post_init__(self) -> None:
        if self.status is not None:
            validate_domain("status", self.status, MEMORY_STATUSES)


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
    status: str
    revision: int
    content_hash: str
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        validate_domain("type", self.type, MEMORY_TYPES)
        validate_domain("scope", self.scope, MEMORY_SCOPES)
        validate_domain("status", self.status, MEMORY_STATUSES)

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
    status: str = "deleted"

    def __post_init__(self) -> None:
        validate_domain("status", self.status, MEMORY_STATUSES)

    def to_dict(self) -> dict:
        return {"id": str(self.id), "revision": self.revision, "content_hash": self.content_hash, "status": self.status}


def record_from_dict(values: dict) -> MemoryRecord:
    return MemoryRecord(UUID(values["id"]), values["type"], values["scope"], values.get("project"), values["content"], values["importance"], values["confidence"], values["pinned"], tuple(values["tags"]), values["status"], values["revision"], values["content_hash"], values["created_at"], values["updated_at"])


def delete_result_from_dict(values: dict) -> DeleteResult:
    return DeleteResult(UUID(values["id"]), values["revision"], values["content_hash"], values["status"])
