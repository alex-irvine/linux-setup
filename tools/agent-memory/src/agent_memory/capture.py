from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
import re
from contextlib import contextmanager
from pathlib import Path

from .git_sync import GitSync, VAULT_RELPATH
from .model import AddRequest, ListQuery, MEMORY_SCOPES, MEMORY_TYPES, MemoryError, UpdateRequest, normalize_content, utc_now
from .ollama import DegradedStatus
from .rank import cosine


# Automatic captures keep only what changes how future work is done. A
# fact about finished work is in its commit, ticket or code; it can still be
# stored on purpose with `memoryctl add` or the memory_add tool.
CAPTURED_TYPES = frozenset({"preference", "correction", "decision", "lesson", "convention"})

# A capture or sync that fails this many times moves to outbox/failed with
# its last error, instead of being retried every run forever.
MAX_ATTEMPTS = 10


class ProviderUnavailable(RuntimeError):
    """The review or embedding provider cannot be reached; nothing is wrong with the capture."""


def log(message: str) -> None:
    print(f"agent-memory worker: {message}", file=sys.stderr, flush=True)


def require(result, what: str):
    """Pass a provider result through, or raise the error the worker retries on."""
    if isinstance(result, DegradedStatus):
        if result.fallback:
            raise ProviderUnavailable(f"{what}: {result.reason}")
        raise RuntimeError(f"{what}: {result.reason}")
    return result


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
        self.ready, self.running, self.done, self.failed = (self.root / name for name in ("ready", "running", "done", "failed"))
        self.lock_path = self.root / "outbox.lock"
        for path in (self.ready, self.running, self.done, self.failed): path.mkdir(parents=True, exist_ok=True)

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

    def claim(self, kinds: set[str] | None = None) -> tuple[Path, dict] | None:
        with self.locked():
            # Sync jobs go first, so a capture backlog never holds back
            # committing what is already accepted.
            envelopes = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in self.ready.glob("*.json")]
            for path, envelope in sorted(envelopes, key=lambda item: (item[1]["kind"] != "sync", item[1]["created_at"])):
                if kinds is not None and envelope["kind"] not in kinds:
                    continue
                if envelope["next_attempt_at"] <= time.time():
                    envelope["claimed_at"] = time.time()
                    atomic_json(path, envelope)
                    running = self.running / path.name
                    self._move(path, running)
                    return running, envelope
        return None

    def finish(self, path: Path, envelope: dict, retry: bool = False, error: str | None = None) -> str:
        """Move a claimed envelope on and return where it went: done, ready or failed."""
        with self.locked():
            envelope.pop("claimed_at", None)
            state = "done"
            if retry:
                envelope["attempts"] += 1
                envelope["last_error"] = error
                envelope["next_attempt_at"] = time.time() + min(300, 2 ** envelope["attempts"])
                state = "failed" if envelope["attempts"] >= MAX_ATTEMPTS else "ready"
            atomic_json(path, envelope)
            self._move(path, getattr(self, state) / path.name)
            return state

    def release(self, path: Path, envelope: dict) -> None:
        with self.locked():
            envelope.pop("claimed_at", None)
            atomic_json(path, envelope)
            self._move(path, self.ready / path.name)

    def has_sync(self) -> bool:
        with self.locked():
            return any(json.loads(path.read_text(encoding="utf-8")).get("kind") == "sync" for directory in (self.ready, self.running) for path in directory.glob("*.json"))

    def counts(self) -> dict:
        with self.locked(): return {name: len(list(path.glob("*.json"))) for name, path in (("ready", self.ready), ("running", self.running), ("done", self.done), ("failed", self.failed))}


class Worker:
    def __init__(self, service, home: Path, repo: Path | None = None) -> None:
        self.service, self.home, self.outbox, self.repo = service, home, Outbox(home), repo
        self.provider_down = None
        self.outbox.recover()

    def _sync_payload(self) -> dict | None:
        # The vault is normally reached through a stowed symlink
        # (~/.agents/memory), so the repository is found from its real path.
        vault = self.service.store.vault.resolve()
        repo = (self.repo or vault).resolve()
        while repo != repo.parent and not (repo / ".git").exists(): repo = repo.parent
        if not (repo / ".git").exists() or not vault.is_relative_to(repo): return None
        return {"repo": str(repo), "vault_relpath": str(VAULT_RELPATH)} if vault.relative_to(repo) == VAULT_RELPATH else None

    def queue_sync(self) -> None:
        payload = self._sync_payload()
        if payload and not self.outbox.has_sync(): self.outbox.enqueue("sync", payload)

    def ensure_dirty_sync(self) -> None:
        if self.service.store.sync_dirty() and not self.outbox.has_sync(): self.queue_sync()

    def _capture(self, payload: dict, report: dict, envelope_id: str) -> None:
        if payload.get("event") != "completed_work" or payload.get("version") != 1 or payload.get("client") not in {"claude", "opencode", "codex", "hermes"} or not isinstance(payload.get("evidence"), dict):
            report["rejected_by_reason"].append("invalid_capture_event"); return
        # Hooks omit a payload ID. The persisted queue ID is unique per job and
        # remains stable across retries and recovery of interrupted workers.
        candidate_id = payload.get("id") or envelope_id
        evidence = payload["evidence"]
        if unsafe_reason(" ".join(str(value) for value in evidence.values())):
            report["rejected_by_reason"].append("unsafe_evidence"); return
        if self.provider_down is None:
            self.provider_down = self.service.ollama.available() or False
        if self.provider_down:
            raise ProviderUnavailable(self.provider_down.reason)
        review = require(self.service.ollama.review_capture(payload), "capture review")
        candidate, reason = reviewed_candidate(payload, review)
        if reason:
            report["rejected_by_reason"].append(reason); return
        assert candidate is not None
        if candidate["type"] not in CAPTURED_TYPES:
            report["rejected_by_reason"].append("not_captured_type"); return
        content = candidate["content"]
        explicit = candidate["type"] in {"preference", "correction"} and bool(payload.get("explicit_user"))
        if candidate["confidence"] < 0.8 and not explicit:
            report["rejected_by_reason"].append("low_confidence"); return
        records = self.service.list(ListQuery(status="active"))
        if any(normalize_content(record.content) == normalize_content(content) for record in records): report["rejected_by_reason"].append("duplicate"); return
        embedded, vectors = require(self.service.similar_vectors(content, records), "capture embedding")
        for prior in records:
            vector = vectors.get(str(prior.id))
            if vector is None or cosine(embedded.vectors[0], vector) < 0.97:
                continue
            if str(prior.id) in candidate["supersedes"]:
                continue
            relation = require(self.service.ollama.review_relation(content, prior.content), "capture relation review")
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
        if created.content == content:
            self.service.index.remember_embeddings([created], embedded.vectors, embedded.model)
        report["accepted"].append(candidate_id)
        self.queue_sync()

    def run(self, drain: bool, limit: int | None = None) -> dict:
        self.ensure_dirty_sync()
        report = {"accepted": [], "rejected_by_reason": [], "sync": None, "retrying": 0, "failed": 0,
                  "provider_unavailable": None, "accepted_sync_note": None}
        processed = 0
        kinds: set[str] | None = None
        self.provider_down = None
        while True:
            claimed = self.outbox.claim(kinds)
            if not claimed: break
            path, envelope = claimed
            retry, error_text = False, None
            try:
                if envelope["kind"] == "capture": self._capture(envelope["payload"], report, envelope["id"])
                else:
                    marker = self.home / "sync-paused.json"
                    if marker.exists(): report["sync"] = {"paused": True, "reason": json.loads(marker.read_text(encoding="utf-8"))["reason"]}; self.outbox.release(path, envelope); break
                    payload = envelope["payload"]
                    sync = GitSync(self.service.store.lock_path).run(Path(payload["repo"]), Path(payload["vault_relpath"]), self.service.reconcile)
                    report["sync"] = sync.to_dict()
                    if sync.pushed: self.service.store.acknowledge_sync()
                    retry = sync.retryable
                    if retry: report["retrying"] += 1; error_text = sync.error
            except ProviderUnavailable as error:
                # Not the capture's fault: it keeps its attempts and waits for
                # the next run, while sync jobs still run in this one.
                self.outbox.release(path, envelope)
                report["provider_unavailable"] = str(error)
                log(f"captures wait for the next run: {error}")
                kinds = {"sync"}
                continue
            except MemoryError as error:
                report["rejected_by_reason"].append(error.code)
            except (OSError, ValueError, RuntimeError) as error:
                retry = True; report["retrying"] += 1; error_text = f"{type(error).__name__}: {error}"
            state = self.outbox.finish(path, envelope, retry, error_text)
            if retry:
                log(f"{envelope['kind']} {envelope['id'][:12]} failed attempt {envelope['attempts']}/{MAX_ATTEMPTS}: {error_text}")
                if state == "failed":
                    report["retrying"] -= 1; report["failed"] += 1
                    log(f"{envelope['kind']} {envelope['id'][:12]} moved to outbox/failed")
            processed += 1
            if (limit is not None and processed >= limit) or (limit is None and not drain): break
        report["outbox"] = self.outbox.counts()
        return report
