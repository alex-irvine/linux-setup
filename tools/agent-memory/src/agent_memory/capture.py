from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from .git_sync import GitSync
from .model import AddRequest, UpdateRequest, normalize_content, utc_now
from .ollama import DegradedStatus


def unsafe_reason(content: str) -> str | None:
    lowered = content.lower()
    checks = (("secret", ("api key", "api_key", "sk-", "password=", "token=")),
              ("prompt_injection", ("ignore previous instructions", "system prompt", "jailbreak")),
              ("raw_transcript", ("user:", "assistant:")),
              ("private_response", ("http/1.", "set-cookie:", "private response")),
              ("transient", ("in progress", "task status", "todo", "temporary")))
    return next((reason for reason, markers in checks if any(marker in lowered for marker in markers)), None)


class Outbox:
    def __init__(self, home: Path) -> None:
        self.root = home / "outbox"
        self.ready, self.running, self.done = (self.root / name for name in ("ready", "running", "done"))
        for path in (self.ready, self.running, self.done):
            path.mkdir(parents=True, exist_ok=True)

    def enqueue(self, kind: str, payload: dict) -> dict:
        if kind not in {"capture", "sync"}:
            raise ValueError("unsupported outbox kind")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        envelope = {"id": hashlib.sha256((encoded + utc_now()).encode()).hexdigest(), "kind": kind,
                    "created_at": utc_now(), "attempts": 0, "next_attempt_at": 0,
                    "payload_hash": hashlib.sha256(encoded.encode()).hexdigest(), "payload": payload}
        descriptor, temporary = tempfile.mkstemp(prefix=".outbox-", dir=self.ready)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(envelope, file, sort_keys=True, separators=(",", ":"))
            file.flush()
            os.fsync(file.fileno())
        destination = self.ready / f"{envelope['id']}.json"
        os.replace(temporary, destination)
        return envelope

    def recover(self) -> None:
        for path in self.running.glob("*.json"):
            os.replace(path, self.ready / path.name)

    def counts(self) -> dict:
        return {name: len(list(path.glob("*.json"))) for name, path in (("ready", self.ready), ("running", self.running), ("done", self.done))}


class Worker:
    def __init__(self, service, home: Path, repo: Path | None = None) -> None:
        self.service, self.home, self.outbox, self.repo = service, home, Outbox(home), repo
        self.outbox.recover()

    def _sync_payload(self) -> dict:
        repo = self.repo or self.service.store.vault
        while repo != repo.parent and not (repo / ".git").exists():
            repo = repo.parent
        return {"repo": str(repo), "vault_relpath": str(self.service.store.vault.relative_to(repo))}

    def queue_sync(self) -> None:
        payload = self._sync_payload()
        if (Path(payload["repo"]) / ".git").exists():
            self.outbox.enqueue("sync", payload)

    def _capture(self, payload: dict, report: dict) -> None:
        candidate_id, content = payload.get("id", "capture"), payload.get("content", "")
        reason = unsafe_reason(content)
        if reason:
            report["rejected_by_reason"].append(reason)
            return
        review = self.service.ollama.review_capture(payload)
        if not isinstance(review, DegradedStatus) and not review["accept"]:
            report["rejected_by_reason"].append("review_rejected")
            return
        records = self.service.list(__import__("agent_memory.model", fromlist=["ListQuery"]).ListQuery(status="active"))
        if any(normalize_content(record.content) == normalize_content(content) for record in records):
            report["rejected_by_reason"].append("duplicate")
            return
        capture_ids_path = self.home / "capture-ids.json"
        capture_ids = json.loads(capture_ids_path.read_text(encoding="utf-8")) if capture_ids_path.exists() else {}
        if payload.get("supersedes"):
            prior = next((record for record in records if str(record.id) == capture_ids.get(payload["supersedes"])), None)
            if prior:
                self.service.update(UpdateRequest(prior.id, prior.revision, prior.content_hash, f"capture-supersede-{candidate_id}", status="superseded"))
        created = self.service.add(AddRequest(f"capture-{candidate_id}", payload.get("type", "fact"), payload.get("scope", "global"), content,
                                               payload.get("project"), payload.get("importance", 0.5), payload.get("confidence", 1.0), False, tuple(payload.get("tags", ()))))
        capture_ids[candidate_id] = str(created.id)
        capture_ids_path.write_text(json.dumps(capture_ids, sort_keys=True), encoding="utf-8")
        report["accepted"].append(candidate_id)
        self.queue_sync()

    def run(self, drain: bool) -> dict:
        reconciled = self.service.reconcile()
        if reconciled.external_edits:
            self.queue_sync()
        report = {"accepted": [], "rejected_by_reason": [], "sync": None, "retrying": 0, "accepted_sync_note": None}
        paths = sorted(self.outbox.ready.glob("*.json"), key=lambda path: json.loads(path.read_text(encoding="utf-8"))["created_at"])
        for path in paths if drain else paths[:1]:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if envelope["next_attempt_at"] > time.time():
                continue
            running = self.outbox.running / path.name
            os.replace(path, running)
            try:
                if envelope["kind"] == "capture":
                    self._capture(envelope["payload"], report)
                else:
                    payload = envelope["payload"]
                    paused = self.home / "sync-paused.json"
                    if paused.exists():
                        report["sync"] = {"paused": True, "reason": json.loads(paused.read_text())["reason"]}
                        os.replace(running, self.outbox.ready / running.name)
                        continue
                    else:
                        sync = GitSync(self.service.store.lock_path).run(Path(payload["repo"]), Path(payload["vault_relpath"]))
                        report["sync"] = sync.to_dict()
                        report["sync"]["reconciled"] = bool(reconciled.external_edits)
                        if sync.retryable:
                            raise RuntimeError(sync.error)
                        if sync.commit_created:
                            changed = GitSync._git(Path(payload["repo"]), "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.splitlines()
                            report["accepted_sync_note"] = Path(changed[-1]).name
                os.replace(running, self.outbox.done / running.name)
            except (OSError, ValueError, RuntimeError) as error:
                envelope["attempts"] += 1
                envelope["next_attempt_at"] = time.time() + min(300, 2 ** envelope["attempts"])
                running.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8")
                os.replace(running, self.outbox.ready / running.name)
                report["retrying"] += 1
        report["outbox"] = self.outbox.counts()
        return report
