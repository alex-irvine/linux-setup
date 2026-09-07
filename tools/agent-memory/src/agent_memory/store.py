from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from . import frontmatter
from .index import MemoryIndex
from .model import (AddRequest, DeleteRequest, DeleteResult, ListQuery, MemoryError,
                    MemoryRecord, SearchQuery, SearchResult, UpdateRequest, content_hash,
                    delete_result_from_dict, record_from_dict, request_hash, utc_now, uuid7)


class MarkdownStore:
    def __init__(self, vault: Path, home: Path) -> None:
        self.vault = vault
        self.notes = vault / "notes"
        self.home = home
        self.lock_path = home / "memory.lock"
        self.journal_path = home / "mutations.jsonl"
        self.notes.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _path(self, memory_id: UUID) -> Path:
        return self.notes / f"{memory_id}.md"

    def get(self, memory_id: UUID) -> MemoryRecord:
        path = self._path(memory_id)
        if not path.exists():
            raise MemoryError("not_found", f"memory {memory_id} does not exist")
        return record_from_dict(frontmatter.load(path.read_text(encoding="utf-8")))

    def _check_idempotency(self, index: MemoryIndex, request_id: str, payload_hash: str) -> MemoryRecord | DeleteResult | None:
        existing = index.idempotency(request_id)
        if existing is not None:
            stored_hash, stored_result = existing
        else:
            stored_hash, stored_result = self._journal_idempotency(request_id)
        if stored_hash is None:
            return None
        if stored_hash != payload_hash:
            raise MemoryError("idempotency_conflict", "request_id was reused with a different payload")
        result = json.loads(stored_result)
        return delete_result_from_dict(result) if result["status"] == "deleted" else record_from_dict(result)

    def _journal_idempotency(self, request_id: str) -> tuple[str | None, str | None]:
        if not self.journal_path.exists():
            return None, None
        with self.journal_path.open(encoding="utf-8") as journal:
            entries = [json.loads(line) for line in journal if line.strip()]
        for entry in reversed(entries):
            if entry.get("request_id") == request_id:
                return entry["payload_hash"], json.dumps(entry["result"], sort_keys=True, separators=(",", ":"))
        return None, None

    def _write_note(self, record: MemoryRecord) -> None:
        destination = self._path(record.id)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{record.id}.", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(frontmatter.dump(record))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, destination)
            directory = os.open(destination.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _journal(self, operation: str, record: MemoryRecord, request_id: str, payload_hash: str, result: MemoryRecord | DeleteResult) -> None:
        result_data = result.to_dict()
        entry = json.dumps({"operation": operation, "id": str(record.id), "revision": record.revision, "content_hash": record.content_hash, "status": result_data["status"], "request_id": request_id, "payload_hash": payload_hash, "result": result_data, "at": utc_now()}, sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = os.open(self.journal_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, entry.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def add(self, request: AddRequest, index: MemoryIndex) -> MemoryRecord:
        payload_hash = request_hash("add", {**request.__dict__, "tags": list(request.tags)})
        with self._locked():
            replay = self._check_idempotency(index, request.request_id, payload_hash)
            if replay is not None:
                if isinstance(replay, MemoryRecord):
                    return replay
                raise MemoryError("idempotency_conflict", "request_id belongs to a different mutation")
            now = utc_now()
            record = MemoryRecord(uuid7(), request.type, request.scope, request.project, request.content, request.importance, request.confidence, request.pinned, tuple(request.tags), "active", 1, content_hash(request.content), now, now)
            self._write_note(record)
            self._journal("add", record, request.request_id, payload_hash, record)
            index.upsert(record)
            index.remember_idempotency(request.request_id, payload_hash, record.to_dict())
            return record

    def update(self, request: UpdateRequest, index: MemoryIndex) -> MemoryRecord:
        payload_hash = request_hash("update", {**request.__dict__, "memory_id": str(request.memory_id), "tags": list(request.tags) if request.tags is not None else None})
        with self._locked():
            replay = self._check_idempotency(index, request.request_id, payload_hash)
            if replay is not None:
                if isinstance(replay, MemoryRecord):
                    return replay
                raise MemoryError("idempotency_conflict", "request_id belongs to a different mutation")
            current = self.get(request.memory_id)
            self._assert_current(current, request.expected_revision, request.expected_content_hash)
            content = request.content if request.content is not None else current.content
            record = MemoryRecord(current.id, current.type, current.scope, current.project, content, request.importance if request.importance is not None else current.importance, request.confidence if request.confidence is not None else current.confidence, request.pinned if request.pinned is not None else current.pinned, tuple(request.tags) if request.tags is not None else current.tags, request.status if request.status is not None else current.status, current.revision + 1, content_hash(content), current.created_at, utc_now())
            self._write_note(record)
            self._journal("update", record, request.request_id, payload_hash, record)
            index.upsert(record)
            index.remember_idempotency(request.request_id, payload_hash, record.to_dict())
            return record

    def delete(self, request: DeleteRequest, index: MemoryIndex) -> DeleteResult:
        payload_hash = request_hash("delete", {**request.__dict__, "memory_id": str(request.memory_id)})
        with self._locked():
            replay = self._check_idempotency(index, request.request_id, payload_hash)
            if replay is not None:
                if isinstance(replay, DeleteResult):
                    return replay
                raise MemoryError("idempotency_conflict", "request_id belongs to a different mutation")
            current = self.get(request.memory_id)
            self._assert_current(current, request.expected_revision, request.expected_content_hash)
            self._path(current.id).unlink()
            directory = os.open(self.notes, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            result = DeleteResult(current.id, current.revision, current.content_hash)
            self._journal("delete", current, request.request_id, payload_hash, result)
            index.remove(str(current.id))
            index.remember_idempotency(request.request_id, payload_hash, result.to_dict())
            return result

    @staticmethod
    def _assert_current(current: MemoryRecord, revision: int, digest: str) -> None:
        if current.revision != revision or current.content_hash != digest:
            raise MemoryError("revision_conflict", "memory revision or content hash no longer matches")


class MemoryService:
    def __init__(self, store: MarkdownStore, index: MemoryIndex) -> None:
        self.store, self.index = store, index

    def add(self, request: AddRequest) -> MemoryRecord:
        return self.store.add(request, self.index)

    def get(self, memory_id: UUID) -> MemoryRecord:
        return self.store.get(memory_id)

    def list(self, query: ListQuery) -> list[MemoryRecord]:
        return self.index.list(query)

    def search(self, query: SearchQuery) -> SearchResult:
        return self.index.search_lexical(query)

    def update(self, request: UpdateRequest) -> MemoryRecord:
        return self.store.update(request, self.index)

    def delete(self, request: DeleteRequest) -> DeleteResult:
        return self.store.delete(request, self.index)
