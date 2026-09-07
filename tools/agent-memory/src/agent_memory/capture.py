from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
import re
from contextlib import contextmanager
from pathlib import Path

from .git_sync import GitSync, VAULT_RELPATH
from .model import AddRequest, ListQuery, MEMORY_SCOPES, MEMORY_TYPES, UpdateRequest, normalize_content, utc_now
from .ollama import DegradedStatus
from .rank import cosine


def unsafe_reason(content: str) -> str | None:
    lowered = content.lower()
    if len(content) > 4000:
        return "bulk_output"
    if re.search(r"(?:api[_-]?key|token|password|secret|authorization)\s*[:=]\s*(?:bearer\s+)?\S+", content, re.I) or "-----begin " in lowered and "private key-----" in lowered or re.search(r"\b(?:home|path|aws_[a-z_]+)\s*=", content, re.I):
        return "secret"
    checks = (("prompt_injection", ("ignore previous instructions", "ignore all prior", "system prompt", "jailbreak", "developer message")), ("raw_transcript", ("user:", "assistant:", "role: assistant", "role: user")), ("private_response", ("http/1.", "set-cookie:", "private response", "content-type: application/json")), ("transient", ("in progress", "task status", "todo", "temporary", "working on")))
    return next((reason for reason, markers in checks if any(marker in lowered for marker in markers)), None)


def reviewed_candidate(event: dict, review: dict) -> tuple[dict | None, str | None]:
    """Validate untrusted local-model output before it crosses into canonical data."""
    required = {"type", "scope", "project", "content", "importance", "confidence", "tags", "durability", "supersedes"}
    if not isinstance(review, dict) or set(review) != required:
        return None, "review_malformed"
    if review["type"] not in MEMORY_TYPES or review["scope"] not in MEMORY_SCOPES:
        return None, "review_invalid_domain"
    if not isinstance(review["content"], str) or not normalize_content(review["content"]):
        return None, "review_empty"
    if not isinstance(review["importance"], (int, float)) or not 0 <= review["importance"] <= 1 or not isinstance(review["confidence"], (int, float)) or not 0 <= review["confidence"] <= 1:
        return None, "review_invalid_scores"
    if not isinstance(review["tags"], list) or not all(isinstance(tag, str) and tag for tag in review["tags"]) or not isinstance(review["supersedes"], list) or not all(isinstance(item, str) for item in review["supersedes"]):
        return None, "review_invalid_metadata"
    if review["scope"] == "project" and not isinstance(review["project"], str):
        return None, "review_invalid_project"
    if review["scope"] == "global" and review["project"] is not None:
        return None, "review_invalid_project"
    if review["durability"] is not True:
        return None, "not_durable"
    reason = unsafe_reason(review["content"])
    if reason:
        return None, reason
    return review, None


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, sort_keys=True, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class Outbox:
    def __init__(self, home: Path) -> None:
        self.root = home / "outbox"
        self.ready, self.running, self.done = (self.root / name for name in ("ready", "running", "done"))
        self.lock_path = self.root / "outbox.lock"
        for path in (self.ready, self.running, self.done): path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def locked(self):
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        os.replace(source, destination)
        for directory_path in {source.parent, destination.parent}:
            directory = os.open(directory_path, os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)

    def enqueue(self, kind: str, payload: dict) -> dict:
        if kind not in {"capture", "sync"}: raise ValueError("unsupported outbox kind")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        envelope = {"id": hashlib.sha256((encoded + utc_now()).encode()).hexdigest(), "kind": kind, "created_at": utc_now(), "attempts": 0, "next_attempt_at": 0, "payload_hash": hashlib.sha256(encoded.encode()).hexdigest(), "payload": payload}
        with self.locked(): atomic_json(self.ready / f"{envelope['id']}.json", envelope)
        return envelope

    def recover(self, stale_after: int = 300) -> None:
        with self.locked():
            now = time.time()
            for path in self.running.glob("*.json"):
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if not envelope.get("claimed_at") or now - envelope["claimed_at"] >= stale_after:
                    envelope.pop("claimed_at", None)
                    atomic_json(path, envelope)
                    self._move(path, self.ready / path.name)

    def claim(self) -> tuple[Path, dict] | None:
        with self.locked():
            candidates = sorted(self.ready.glob("*.json"), key=lambda path: json.loads(path.read_text(encoding="utf-8"))["created_at"])
            for path in candidates:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if envelope["next_attempt_at"] <= time.time():
                    envelope["claimed_at"] = time.time()
                    atomic_json(path, envelope)
                    running = self.running / path.name
                    self._move(path, running)
                    return running, envelope
        return None

    def finish(self, path: Path, envelope: dict, retry: bool = False) -> None:
        with self.locked():
            envelope.pop("claimed_at", None)
            destination = self.ready / path.name if retry else self.done / path.name
            if retry:
                envelope["attempts"] += 1
                envelope["next_attempt_at"] = time.time() + min(300, 2 ** envelope["attempts"])
            atomic_json(path, envelope)
            self._move(path, destination)

    def release(self, path: Path, envelope: dict) -> None:
        with self.locked():
            envelope.pop("claimed_at", None)
            atomic_json(path, envelope)
            self._move(path, self.ready / path.name)

    def has_sync(self) -> bool:
        with self.locked():
            return any(json.loads(path.read_text(encoding="utf-8")).get("kind") == "sync" for directory in (self.ready, self.running) for path in directory.glob("*.json"))

    def counts(self) -> dict:
        with self.locked(): return {name: len(list(path.glob("*.json"))) for name, path in (("ready", self.ready), ("running", self.running), ("done", self.done))}


class Worker:
    def __init__(self, service, home: Path, repo: Path | None = None) -> None:
        self.service, self.home, self.outbox, self.repo = service, home, Outbox(home), repo
        self.outbox.recover()

    def _sync_payload(self) -> dict | None:
        repo = self.repo or self.service.store.vault
        while repo != repo.parent and not (repo / ".git").exists(): repo = repo.parent
        if not (repo / ".git").exists() or not self.service.store.vault.is_relative_to(repo): return None
        return {"repo": str(repo), "vault_relpath": str(VAULT_RELPATH)} if self.service.store.vault.relative_to(repo) == VAULT_RELPATH else None

    def queue_sync(self) -> None:
        payload = self._sync_payload()
        if payload and not self.outbox.has_sync(): self.outbox.enqueue("sync", payload)

    def ensure_dirty_sync(self) -> None:
        if self.service.store.sync_dirty() and not self.outbox.has_sync(): self.queue_sync()

    def _capture(self, payload: dict, report: dict) -> None:
        if payload.get("event") != "completed_work" or payload.get("version") != 1 or payload.get("client") not in {"claude", "opencode", "hermes", "pi"} or not isinstance(payload.get("evidence"), dict):
            report["rejected_by_reason"].append("invalid_capture_event"); return
        candidate_id = payload.get("id", "capture")
        evidence = payload["evidence"]
        if unsafe_reason(" ".join(str(value) for value in evidence.values())):
            report["rejected_by_reason"].append("unsafe_evidence"); return
        review = self.service.ollama.review_capture(payload)
        if isinstance(review, DegradedStatus):
            raise RuntimeError("capture reviewer unavailable")
        candidate, reason = reviewed_candidate(payload, review)
        if reason:
            report["rejected_by_reason"].append(reason); return
        assert candidate is not None
        content = candidate["content"]
        explicit = candidate["type"] in {"preference", "correction"} and bool(payload.get("explicit_user"))
        if candidate["confidence"] < 0.8 and not explicit:
            report["rejected_by_reason"].append("low_confidence"); return
        records = self.service.list(ListQuery(status="active"))
        if any(normalize_content(record.content) == normalize_content(content) for record in records): report["rejected_by_reason"].append("duplicate"); return
        embedded = self.service.ollama.embed([content, *[record.content for record in records]])
        if isinstance(embedded, DegradedStatus) or len(embedded.vectors) != len(records) + 1 or not embedded.vectors or any(len(vector) != len(embedded.vectors[0]) for vector in embedded.vectors):
            raise RuntimeError("capture embedding unavailable")
        for prior, vector in zip(records, embedded.vectors[1:]):
            if cosine(embedded.vectors[0], vector) < 0.97:
                continue
            if str(prior.id) in candidate["supersedes"]:
                continue
            relation = self.service.ollama.review_relation(content, prior.content)
            if isinstance(relation, DegradedStatus):
                raise RuntimeError("capture relation reviewer unavailable")
            if relation == "duplicate":
                report["rejected_by_reason"].append("semantic_duplicate"); return
        mapping = self.home / "capture-ids.json"
        with self.outbox.locked():
            capture_ids = json.loads(mapping.read_text(encoding="utf-8")) if mapping.exists() else {}
            for superseded in candidate["supersedes"]:
                prior = next((record for record in records if str(record.id) == superseded), None)
                if prior: self.service.update(UpdateRequest(prior.id, prior.revision, prior.content_hash, f"capture-supersede-{candidate_id}-{prior.id}", status="superseded"))
            created = self.service.add(AddRequest(f"capture-{candidate_id}", candidate["type"], candidate["scope"], content, candidate["project"], candidate["importance"], candidate["confidence"], False, tuple(candidate["tags"]), payload["client"], payload.get("source_session", "unknown"), tuple(candidate["supersedes"])))
            capture_ids[candidate_id] = str(created.id)
            atomic_json(mapping, capture_ids)
        report["accepted"].append(candidate_id)
        self.queue_sync()

    def run(self, drain: bool) -> dict:
        self.ensure_dirty_sync()
        report = {"accepted": [], "rejected_by_reason": [], "sync": None, "retrying": 0, "accepted_sync_note": None}
        while True:
            claimed = self.outbox.claim()
            if not claimed: break
            path, envelope = claimed
            retry = False
            try:
                if envelope["kind"] == "capture": self._capture(envelope["payload"], report)
                else:
                    marker = self.home / "sync-paused.json"
                    if marker.exists(): report["sync"] = {"paused": True, "reason": json.loads(marker.read_text(encoding="utf-8"))["reason"]}; self.outbox.release(path, envelope); break
                    payload = envelope["payload"]
                    sync = GitSync(self.service.store.lock_path).run(Path(payload["repo"]), Path(payload["vault_relpath"]), self.service.reconcile)
                    report["sync"] = sync.to_dict()
                    if sync.pushed: self.service.store.acknowledge_sync()
                    retry = sync.retryable
                    if retry: report["retrying"] += 1
            except (OSError, ValueError, RuntimeError) as error:
                retry = True; report["retrying"] += 1
            self.outbox.finish(path, envelope, retry)
            if not drain: break
        report["outbox"] = self.outbox.counts()
        return report
