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
    source_client: str = "unknown"

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
    scope: str | None = None
    type: str | None = None
    tags: Sequence[str] = ()

    def __post_init__(self) -> None:
        if self.status is not None:
            validate_domain("status", self.status, MEMORY_STATUSES)
        if self.scope is not None:
            validate_domain("scope", self.scope, MEMORY_SCOPES)
        if self.type is not None:
            validate_domain("type", self.type, MEMORY_TYPES)


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
    source_client: str = "unknown"

    def with_computed_hash(self) -> MemoryRecord:
        return MemoryRecord(self.id, self.type, self.scope, self.project, self.content,
                             self.importance, self.confidence, self.pinned, self.tags,
                             self.status, self.revision, content_hash(self.content),
                             self.created_at, self.updated_at, self.source_client)

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
    memories: list[dict]
    semantic_status: str = "unavailable"

    def to_dict(self) -> dict:
        return {"memories": self.memories, "semantic_status": self.semantic_status}


@dataclass(frozen=True)
class PinRequest:
    memory_id: UUID
    expected_revision: int
    expected_content_hash: str
    request_id: str
    pinned: bool


@dataclass(frozen=True)
class ScopeRequest:
    memory_id: UUID
    expected_revision: int
    expected_content_hash: str
    request_id: str
    scope: str
    project: str | None

    def __post_init__(self) -> None:
        validate_domain("scope", self.scope, MEMORY_SCOPES)
        if self.scope == "project" and not self.project:
            raise MemoryError("invalid_project", "project scope requires a project")


@dataclass(frozen=True)
class FeedbackRequest:
    memory_id: UUID
    request_id: str
    rating: str

    def __post_init__(self) -> None:
        if self.rating not in {"positive", "negative"}:
            raise MemoryError("invalid_rating", "rating must be positive or negative")


@dataclass(frozen=True)
class InvalidNote:
    path: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RebuildReport:
    active_count: int
    invalid_notes: list[InvalidNote]

    def to_dict(self) -> dict:
        return {"active_count": self.active_count,
                "invalid_notes": [note.to_dict() for note in self.invalid_notes]}


@dataclass(frozen=True)
class ReconcileReport:
    external_edits: list[str]
    invalid_notes: list[InvalidNote]
    excluded_paths: list[str]
    conflict_paths: list[str]

    def to_dict(self) -> dict:
        return {"external_edits": self.external_edits,
                "invalid_notes": [note.to_dict() for note in self.invalid_notes],
                "excluded_paths": self.excluded_paths, "conflict_paths": self.conflict_paths}


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
    return MemoryRecord(UUID(values["id"]), values["type"], values["scope"], values.get("project"), values["content"], values["importance"], values["confidence"], values["pinned"], tuple(values["tags"]), values["status"], values["revision"], values["content_hash"], values["created_at"], values["updated_at"], values.get("source_client", "unknown"))


def delete_result_from_dict(values: dict) -> DeleteResult:
    return DeleteResult(UUID(values["id"]), values["revision"], values["content_hash"], values["status"])
