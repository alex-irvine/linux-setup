from __future__ import annotations

import fcntl
import json
import os
import secrets
import tempfile
import time
from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from . import frontmatter
from .index import MemoryIndex
from .model import (AddRequest, DeleteRequest, DeleteResult, FeedbackRequest, InvalidNote,
                    ListQuery, MemoryError, MemoryRecord, PinRequest, RebuildReport,
                    ReconcileReport, ScopeRequest, SearchQuery, SearchResult, UpdateRequest,
                    content_hash, delete_result_from_dict, record_from_dict, request_hash,
                    utc_now, uuid7)
from .ollama import DegradedStatus, OllamaClient
from .rank import cosine, reciprocal_rank


class MarkdownStore:
    def __init__(self, vault: Path, home: Path) -> None:
        self.vault = vault
        self.notes = vault / "notes"
        self.home = home
        self.lock_path = home / "memory.lock"
        self.journal_path = home / "mutations.jsonl"
        self.audit_path = home / "audit.jsonl"
        self.authorizations_path = home / "authorizations.json"
        self.conflicts = vault / "Conflicts"
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
        if "status" not in result:
            raise MemoryError("idempotency_conflict", "request_id belongs to a different mutation")
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

    def _journal_result(self, operation: str, memory_id: str, request_id: str, payload_hash: str, result: dict) -> None:
        entry = json.dumps({"operation": operation, "id": memory_id, "request_id": request_id,
                            "payload_hash": payload_hash, "result": result, "at": utc_now()},
                           sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = os.open(self.journal_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, entry.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def feedback_results(self) -> dict[str, dict]:
        if not self.journal_path.exists():
            return {}
        values = {}
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("operation") == "feedback":
                values[entry["id"]] = entry["result"]
        return values

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
        self._mark_sync_dirty()

    @property
    def sync_state_path(self) -> Path:
        return self.home / "sync-state.json"

    def _sync_state(self) -> dict:
        return json.loads(self.sync_state_path.read_text(encoding="utf-8")) if self.sync_state_path.exists() else {"generation": 0, "acknowledged": 0, "scheduling_error": None}

    def _write_json_atomic(self, path: Path, value: dict) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(value, file, sort_keys=True, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _mark_sync_dirty(self) -> None:
        state = self._sync_state()
        state["generation"] += 1
        self._write_json_atomic(self.sync_state_path, state)

    def sync_dirty(self) -> bool:
        state = self._sync_state()
        return state["generation"] > state["acknowledged"]

    def acknowledge_sync(self) -> None:
        with self._locked():
            state = self._sync_state()
            state["acknowledged"] = state["generation"]
            state["scheduling_error"] = None
            self._write_json_atomic(self.sync_state_path, state)

    def scheduling_failed(self, error: Exception) -> None:
        with self._locked():
            state = self._sync_state()
            state["scheduling_error"] = str(error)
            self._write_json_atomic(self.sync_state_path, state)

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
            try:
                self._assert_current(current, request.expected_revision, request.expected_content_hash)
            except MemoryError:
                self._write_conflict(current, request)
                raise
            content = request.content if request.content is not None else current.content
            record = MemoryRecord(current.id, current.type, current.scope, current.project, content, request.importance if request.importance is not None else current.importance, request.confidence if request.confidence is not None else current.confidence, request.pinned if request.pinned is not None else current.pinned, tuple(request.tags) if request.tags is not None else current.tags, request.status if request.status is not None else current.status, current.revision + 1, content_hash(content), current.created_at, utc_now())
            self._write_note(record)
            self._journal("update", record, request.request_id, payload_hash, record)
            index.upsert(record)
            index.remember_idempotency(request.request_id, payload_hash, record.to_dict())
            return record

    def pin(self, request: PinRequest, index: MemoryIndex) -> MemoryRecord:
        return self.update(UpdateRequest(request.memory_id, request.expected_revision,
                           request.expected_content_hash, request.request_id, pinned=request.pinned), index)

    def scope(self, request: ScopeRequest, index: MemoryIndex) -> MemoryRecord:
        payload_hash = request_hash("scope", {**request.__dict__, "memory_id": str(request.memory_id)})
        with self._locked():
            replay = self._check_idempotency(index, request.request_id, payload_hash)
            if replay is not None:
                if isinstance(replay, MemoryRecord):
                    return replay
                raise MemoryError("idempotency_conflict", "request_id belongs to a different mutation")
            current = self.get(request.memory_id)
            try:
                self._assert_current(current, request.expected_revision, request.expected_content_hash)
            except MemoryError:
                self._write_conflict(current, request)
                raise
            record = replace(current, scope=request.scope, project=request.project if request.scope == "project" else None,
                             revision=current.revision + 1, updated_at=utc_now())
            self._write_note(record)
            self._journal("scope", record, request.request_id, payload_hash, record)
            index.upsert(record)
            index.remember_idempotency(request.request_id, payload_hash, record.to_dict())
            return record

    def feedback(self, request: FeedbackRequest, index: MemoryIndex) -> dict:
        payload_hash = request_hash("feedback", {**request.__dict__, "memory_id": str(request.memory_id)})
        with self._locked():
            existing = index.admin_operation(request.request_id)
            if existing is not None:
                if existing[0] != payload_hash:
                    raise MemoryError("idempotency_conflict", "request_id was reused with a different payload")
                return json.loads(existing[1])
            payload, replay = self._journal_idempotency(request.request_id)
            if payload is not None:
                if payload != payload_hash:
                    raise MemoryError("idempotency_conflict", "request_id was reused with a different payload")
                return json.loads(replay)
            self.get(request.memory_id)
            result = index.feedback(str(request.memory_id), request.rating)
            self._journal_result("feedback", str(request.memory_id), request.request_id, payload_hash, result)
            index.remember_admin_operation(request.request_id, payload_hash, result)
            return result

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

    def _write_conflict(self, current: MemoryRecord, request: UpdateRequest | ScopeRequest) -> None:
        self.conflicts.mkdir(parents=True, exist_ok=True)
        preimage = self._journal_preimage(current.id, request.expected_revision, request.expected_content_hash)
        if preimage is None:
            return
        if isinstance(request, UpdateRequest):
            content = request.content if request.content is not None else preimage.content
            candidate = replace(preimage, content=content, content_hash=content_hash(content))
        else:
            candidate = replace(preimage, scope=request.scope,
                                project=request.project if request.scope == "project" else None)
        prefix = self.conflicts / f"{current.id}.{request.request_id}"
        Path(f"{prefix}.preimage.md").write_text(frontmatter.dump(preimage), encoding="utf-8")
        Path(f"{prefix}.candidate.md").write_text(frontmatter.dump(candidate), encoding="utf-8")

    def _journal_preimage(self, memory_id: UUID, revision: int, digest: str) -> MemoryRecord | None:
        if not self.journal_path.exists():
            return None
        for line in reversed(self.journal_path.read_text(encoding="utf-8").splitlines()):
            entry = json.loads(line)
            if entry.get("id") == str(memory_id) and entry.get("revision") == revision and entry.get("content_hash") == digest:
                result = entry.get("result", {})
                if result.get("status") != "deleted":
                    return record_from_dict(result)
        return None

    def _authorizations(self) -> dict:
        return json.loads(self.authorizations_path.read_text(encoding="utf-8")) if self.authorizations_path.exists() else {}

    def authorize(self, action: str, ttl: int) -> dict:
        if action not in {"delete-all", "purge"} or ttl < 1 or ttl > 60:
            raise MemoryError("invalid_request", "authorization action or ttl is invalid")
        with self._locked():
            # Keep positional CLI values unambiguous when argparse sees the token.
            token = secrets.token_urlsafe(24)
            while token.startswith("-"):
                token = secrets.token_urlsafe(24)
            entries = self._authorizations()
            expiry = time.time() + ttl
            entries[token] = {"action": action, "expires_at": expiry}
            self.authorizations_path.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
        return {"token": token, "expires_at": expiry}

    def _consume_token(self, token: str, action: str) -> None:
        entries = self._authorizations()
        entry = entries.pop(token, None)
        self.authorizations_path.write_text(json.dumps(entries, sort_keys=True), encoding="utf-8")
        if entry is None or entry["action"] != action or entry["expires_at"] < time.time():
            raise MemoryError("invalid_authorization", "authorization token is invalid or expired")

    def _audit(self, audit_id: str, action: str, affected_ids: list[str], request_id: str, payload_hash: str, result: dict) -> None:
        with self.audit_path.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps({"id": audit_id, "action": action, "affected_ids": affected_ids,
                                    "request_id": request_id, "payload_hash": payload_hash,
                                    "result": result, "at": utc_now()}, sort_keys=True) + "\n")
            audit.flush()
            os.fsync(audit.fileno())

    def _audit_result(self, request_id: str, payload_hash: str) -> dict | None:
        if not self.audit_path.exists():
            return None
        for line in reversed(self.audit_path.read_text(encoding="utf-8").splitlines()):
            entry = json.loads(line)
            if entry.get("request_id") == request_id:
                if entry.get("payload_hash") != payload_hash:
                    raise MemoryError("idempotency_conflict", "request_id was reused with a different payload")
                return entry["result"]
        return None

    def delete_all(self, request_id: str, token: str, index: MemoryIndex) -> dict:
        payload_hash = request_hash("delete-all", {"request_id": request_id, "token": token})
        with self._locked():
            replay = self._audit_result(request_id, payload_hash)
            if replay is not None:
                return replay
            existing = index.admin_operation(request_id)
            if existing is not None:
                if existing[0] != payload_hash:
                    raise MemoryError("idempotency_conflict", "request_id was reused with a different payload")
                return json.loads(existing[1])
            self._consume_token(token, "delete-all")
            affected = [str(record.id) for record in index.list(ListQuery(status=None))]
            for memory_id in affected:
                path = self._path(UUID(memory_id))
                if path.exists():
                    path.unlink()
            index.clear()
            result = {"affected_ids": affected, "count": len(affected)}
            result["audit_record_id"] = str(uuid7())
            self._audit(result["audit_record_id"], "delete-all", affected, request_id, payload_hash, result)
            index.remember_admin_operation(request_id, payload_hash, result)
            return result

    def purge(self, request_id: str, token: str, memory_id: UUID, digest: str, index: MemoryIndex) -> dict:
        payload_hash = request_hash("purge", {"request_id": request_id, "token": token, "memory_id": str(memory_id), "content_hash": digest})
        with self._locked():
            replay = self._audit_result(request_id, payload_hash)
            if replay is not None:
                return replay
            existing = index.admin_operation(request_id)
            if existing is not None:
                if existing[0] != payload_hash:
                    raise MemoryError("idempotency_conflict", "request_id was reused with a different payload")
                return json.loads(existing[1])
            current = self.get(memory_id)
            if current.content_hash != digest:
                raise MemoryError("revision_conflict", "memory content hash no longer matches")
            self._consume_token(token, "purge")
            self._path(memory_id).unlink()
            index.remove(str(memory_id))
            if self.journal_path.exists():
                entries = [line for line in self.journal_path.read_text(encoding="utf-8").splitlines() if json.loads(line).get("id") != str(memory_id)]
                self.journal_path.write_text("\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
            affected = [str(memory_id)]
            result = {"affected_ids": affected, "count": 1}
            result["audit_record_id"] = str(uuid7())
            self._audit(result["audit_record_id"], "purge", affected, request_id, payload_hash, result)
            index.remember_admin_operation(request_id, payload_hash, result)
            return result

    @staticmethod
    def _assert_current(current: MemoryRecord, revision: int, digest: str) -> None:
        if current.revision != revision or current.content_hash != digest:
            raise MemoryError("revision_conflict", "memory revision or content hash no longer matches")


class MemoryService:
    def __init__(self, store: MarkdownStore, index: MemoryIndex) -> None:
        self.store, self.index, self.ollama = store, index, OllamaClient()

    def add(self, request: AddRequest) -> MemoryRecord:
        return self.store.add(request, self.index)

    def get(self, memory_id: UUID) -> MemoryRecord:
        return self.store.get(memory_id)

    def list(self, query: ListQuery) -> list[MemoryRecord]:
        return self.index.list(query)

    def search(self, query: SearchQuery) -> SearchResult:
        lexical = self.index.search_lexical(query).memories
        lexical_ranks = {record["id"]: rank for rank, record in enumerate(lexical, 1)}
        candidates = self.index.candidates(query)
        embedded = self.ollama.embed([query.query, *[record.content for record in candidates]])
        semantic_ranks: dict[str, int] = {}
        semantic_status = "unavailable"
        if not isinstance(embedded, DegradedStatus):
            semantic_status = "available"
            scored = sorted(zip(candidates, embedded.vectors[1:]), key=lambda item: (-cosine(embedded.vectors[0], item[1]), str(item[0].id)))
            semantic_ranks = {str(record.id): rank for rank, (record, _) in enumerate(scored, 1)}
        by_id = {str(record.id): record for record in candidates}
        hits = []
        for memory_id in set(lexical_ranks) | set(semantic_ranks):
            record = by_id[memory_id]
            lexical_rank, semantic_rank = lexical_ranks.get(memory_id), semantic_ranks.get(memory_id)
            score = (reciprocal_rank(lexical_rank) if lexical_rank else 0) + (reciprocal_rank(semantic_rank) if semantic_rank else 0)
            boosts = []
            if query.project and record.project == query.project:
                boosts.append("project_exact")
                score += 0.001
            if record.pinned:
                boosts.append("pinned")
                score += 0.001
            positive, negative = self.index.feedback_counts(memory_id)
            if positive > negative:
                boosts.append("positive_feedback")
                score += 0.001
            hit = record.to_dict()
            hit.update({"score": score, "lexical_rank": lexical_rank, "semantic_rank": semantic_rank,
                        "boosts": boosts, "explanation": {"rrf": "1 / (60 + rank)", "positive": positive, "negative": negative}})
            hits.append(hit)
        hits.sort(key=lambda hit: (hit["lexical_rank"] is None, -hit["score"], hit["id"]))
        return SearchResult(hits, semantic_status)

    def update(self, request: UpdateRequest) -> MemoryRecord:
        return self.store.update(request, self.index)

    def delete(self, request: DeleteRequest) -> DeleteResult:
        return self.store.delete(request, self.index)

    def pin(self, request: PinRequest) -> MemoryRecord:
        return self.store.pin(request, self.index)

    def scope(self, request: ScopeRequest) -> MemoryRecord:
        return self.store.scope(request, self.index)

    def feedback(self, request: FeedbackRequest) -> dict:
        return self.store.feedback(request, self.index)

    def _notes(self):
        for path in sorted(self.store.notes.glob("*.md")):
            try:
                yield path, record_from_dict(frontmatter.load(path.read_text(encoding="utf-8"))), None
            except (OSError, ValueError, KeyError, TypeError) as error:
                yield path, None, str(error)

    def reconcile(self) -> ReconcileReport:
        edits, invalid, excluded = [], [], []
        for path, record, error in self._notes():
            if record is None:
                invalid.append(InvalidNote(str(path), error or "invalid memory frontmatter"))
                excluded.append(str(path))
                self.index.exclude_path(path, error or "invalid memory frontmatter")
                self.index.remove(path.stem)
            elif record.content_hash != content_hash(record.content):
                computed = record.with_computed_hash()
                edits.append(str(record.id))
                self.store._write_note(computed)
                self.index.upsert(computed, externally_modified=True)
        return ReconcileReport(edits, invalid, excluded, [str(path) for path in sorted(self.store.conflicts.glob("*.md"))] if self.store.conflicts.exists() else [])

    def rebuild(self) -> RebuildReport:
        self.index.clear()
        invalid, active, records = [], 0, []
        for path, record, error in self._notes():
            if record is None:
                invalid.append(InvalidNote(str(path), error or "invalid memory frontmatter"))
                self.index.exclude_path(path, error or "invalid memory frontmatter")
            else:
                self.index.upsert(record.with_computed_hash(), externally_modified=record.content_hash != content_hash(record.content))
                records.append(record)
                if record.status == "active":
                    active += 1
        embedded = self.ollama.embed([record.content for record in records])
        if not isinstance(embedded, DegradedStatus):
            self.index.remember_embeddings(records, embedded.vectors)
        for memory_id, counts in self.store.feedback_results().items():
            self.index.set_feedback(memory_id, counts["positive"], counts["negative"])
        return RebuildReport(active, invalid)

    def maintain(self, security_scan: bool = False, fail_on_finding: bool = False) -> dict:
        reconciled = self.reconcile()
        rebuilt = self.rebuild()
        findings = []
        if security_scan:
            from .capture import unsafe_reason
            for path in sorted(self.store.notes.glob("*.md")):
                reason = unsafe_reason(path.read_text(encoding="utf-8"))
                if reason:
                    findings.append({"path": str(path), "reason": reason})
            if findings and fail_on_finding:
                raise MemoryError("security_findings", "security scan found unsafe content")
        return {"reconcile": reconciled.to_dict(), "rebuild": rebuilt.to_dict(), "security_findings": findings}

    def status(self) -> dict:
        invalid = [InvalidNote(path, "invalid memory frontmatter") for path in self.index.excluded_paths()]
        available = not isinstance(self.ollama.embed(["status"]), DegradedStatus)
        from .capture import Outbox
        paused = self.store.home / "sync-paused.json"
        return {"semantic_status": "available" if available else "unavailable", "invalid_notes": [note.to_dict() for note in invalid],
                "outbox": Outbox(self.store.home).counts(), "sync_paused": json.loads(paused.read_text(encoding="utf-8")) if paused.exists() else None,
                "sync_state": self.store._sync_state()}

    def authorize(self, action: str, ttl: int) -> dict:
        return self.store.authorize(action, ttl)

    def delete_all(self, request_id: str, token: str) -> dict:
        return self.store.delete_all(request_id, token, self.index)

    def purge(self, request_id: str, token: str, memory_id: UUID, digest: str) -> dict:
        return self.store.purge(request_id, token, memory_id, digest, self.index)
