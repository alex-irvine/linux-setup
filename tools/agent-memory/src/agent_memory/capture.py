from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .git_sync import GitSync, VAULT_RELPATH
from .model import AddRequest, ListQuery, UpdateRequest, normalize_content, utc_now
from .ollama import DegradedStatus


def unsafe_reason(content: str) -> str | None:
    lowered = content.lower()
    checks = (("secret", ("api key", "api_key", "sk-", "password=", "token=")), ("prompt_injection", ("ignore previous instructions", "system prompt", "jailbreak")), ("raw_transcript", ("user:", "assistant:")), ("private_response", ("http/1.", "set-cookie:", "private response")), ("transient", ("in progress", "task status", "todo", "temporary")))
    return next((reason for reason, markers in checks if any(marker in lowered for marker in markers)), None)


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
        candidate_id, content = payload.get("id", "capture"), payload.get("content", "")
        reason = unsafe_reason(content)
        if reason: report["rejected_by_reason"].append(reason); return
        review = self.service.ollama.review_capture(payload)
        if not isinstance(review, DegradedStatus) and not review["accept"]: report["rejected_by_reason"].append("review_rejected"); return
        records = self.service.list(ListQuery(status="active"))
        if any(normalize_content(record.content) == normalize_content(content) for record in records): report["rejected_by_reason"].append("duplicate"); return
        mapping = self.home / "capture-ids.json"
        with self.outbox.locked():
            capture_ids = json.loads(mapping.read_text(encoding="utf-8")) if mapping.exists() else {}
            if payload.get("supersedes"):
                prior = next((record for record in records if str(record.id) == capture_ids.get(payload["supersedes"])), None)
                if prior: self.service.update(UpdateRequest(prior.id, prior.revision, prior.content_hash, f"capture-supersede-{candidate_id}", status="superseded"))
            created = self.service.add(AddRequest(f"capture-{candidate_id}", payload.get("type", "fact"), payload.get("scope", "global"), content, payload.get("project"), payload.get("importance", 0.5), payload.get("confidence", 1.0), False, tuple(payload.get("tags", ()))))
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
