from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import UUID

from .model import AddRequest, MemoryError
from .store import MemoryService


QUOTA_DEFERRAL = {
    "status": "deferred",
    "reason": "quota_exhausted",
    "quota_limit": 1000,
    "quota_used": 1000,
    "reported_reset": "2026-10-01T00:00:00+00:00",
    "next_action": "post-reset delta export",
}


class MigrationService:
    """Imports immutable source snapshots while retaining an append-only audit ledger."""

    def __init__(self, service: MemoryService, home: Path, archive: Path | None = None,
                 hermes: Path | None = None, claude: Path | None = None,
                 project_map: Path | None = None) -> None:
        self.service = service
        self.home = home
        root = service.store.vault.parents[2] if len(service.store.vault.parents) >= 3 else Path.home() / "dotfiles"
        self.archive = archive or root / "docs/cross-provider-memory/archive-2026-07-22"
        self.hermes = hermes or Path.home() / ".hermes/memories"
        self.claude = claude or Path.home() / ".claude/projects"
        self.project_map = project_map or Path.home() / ".mem0/project_map.json"

    def _batch_dir(self, batch: str) -> Path:
        if not batch or "/" in batch or ".." in batch:
            raise MemoryError("invalid_request", "batch must be a simple identifier")
        return self.home / "snapshots" / batch

    def _manifest_path(self, batch: str) -> Path:
        return self._batch_dir(batch) / "manifest.json"

    def _ledger_path(self, batch: str) -> Path:
        return self._batch_dir(batch) / "ledger.jsonl"

    def _sources(self) -> list[tuple[str, Path]]:
        sources = [("archive", path) for path in sorted(self.archive.glob("*.md"))]
        sources.extend(("hermes", self.hermes / name) for name in ("MEMORY.md", "USER.md")
                       if (self.hermes / name).is_file())
        sources.extend(("claude", path) for path in sorted(self.claude.glob("**/memory/*.md")))
        return sources

    @staticmethod
    def _hash(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def snapshot(self, batch: str) -> dict:
        directory = self._batch_dir(batch)
        manifest_path = self._manifest_path(batch)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return {"batch": batch, "source_files": len(manifest["sources"]), "snapshot": "existing"}
        raw_directory = directory / "raw"
        raw_directory.mkdir(parents=True, exist_ok=False)
        entries = []
        for number, (kind, path) in enumerate(self._sources()):
            # Read bytes once before parsing; every import works only from this copy.
            raw = path.read_bytes()
            relative = f"raw/{number:04d}.bin"
            destination = directory / relative
            destination.write_bytes(raw)
            entries.append({"source_kind": kind, "source_identity": str(path),
                            "source_hash": self._hash(raw), "raw_snapshot": relative})
        manifest = {"batch": batch, "sources": entries,
                    "project_map_hash": self._hash(self.project_map.read_bytes()) if self.project_map.is_file() else None}
        self._write_json_new(manifest_path, manifest)
        return {"batch": batch, "source_files": len(entries), "snapshot": "created"}

    @staticmethod
    def _write_json_new(path: Path, value: dict) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(value, file, sort_keys=True, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary, path)
        except FileExistsError:
            raise MemoryError("snapshot_exists", f"immutable snapshot already exists: {path}")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _manifest(self, batch: str) -> dict:
        path = self._manifest_path(batch)
        if not path.exists():
            raise MemoryError("not_found", "migration snapshot does not exist")
        return json.loads(path.read_text(encoding="utf-8"))

    def _rows(self, batch: str) -> list[dict]:
        path = self._ledger_path(batch)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def _append(self, batch: str, row: dict) -> None:
        path = self._ledger_path(batch)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _row(entry: dict, **values) -> dict:
        return {"source_kind": entry["source_kind"], "source_identity": entry["source_identity"],
                "source_hash": entry["source_hash"], "cursor": None, "raw_snapshot": entry["raw_snapshot"], "raw_count": 1 if entry["raw_snapshot"] else 0,
                "imported_ids": [], "duplicates": [], "conflicts": [], "failures": [],
                "deferred": None, "waiver": None, **values}

    def _latest_local(self, batch: str) -> dict[str, dict]:
        latest = {}
        for row in self._rows(batch):
            if row["source_kind"] != "hosted":
                latest[row["source_identity"]] = row
        return latest

    @staticmethod
    def _contradiction_key(text: str) -> str | None:
        normalized = " ".join(text.lower().split())
        if " enabled" in normalized or " disabled" in normalized:
            return hashlib.sha256(normalized.replace(" enabled", "").replace(" disabled", "").encode("utf-8")).hexdigest()
        return None

    def disposition(self, batch: str, source_identity: str, action: str, reason: str,
                    decision: str, note_id: str | None = None) -> dict:
        """Append a user-approved exclusion or waiver without changing snapshots."""
        entries = {entry["source_identity"]: entry for entry in self._manifest(batch)["sources"]}
        entry = entries.get(source_identity)
        if entry is None or action not in {"defer", "waive"}:
            raise MemoryError("invalid_request", "unknown migration source or disposition")
        latest = self._latest_local(batch).get(source_identity)
        if latest is None:
            raise MemoryError("invalid_request", "source has no prior migration accounting")
        if action == "defer":
            if note_id is None or latest.get("imported_ids") != [note_id]:
                raise MemoryError("invalid_request", "note id does not match the imported source")
            path = self.service.store._path(UUID(note_id))
            if not path.exists():
                raise MemoryError("not_found", "generated note does not exist")
            path.unlink()
            row = self._row(entry, deferred={"status": "deferred", "reason": reason, "decision": decision})
        else:
            row = self._row(entry, imported_ids=latest.get("imported_ids", []),
                            duplicates=latest.get("duplicates", []),
                            waiver={"status": "waived", "reason": reason, "decision": decision})
        self._append(batch, row)
        return {"batch": batch, "source_identity": source_identity, "action": action, "reason": reason}

    def import_local(self, batch: str, stop_after: int | None = None) -> dict:
        manifest = self._manifest(batch)
        latest = self._latest_local(batch)
        all_rows = self._rows(batch)
        hashes = {row["source_hash"]: row for row in all_rows if row.get("imported_ids")}
        contradictions = {row.get("contradiction_key"): row for row in all_rows if row.get("contradiction_key")}
        processed = imported = 0
        for entry in manifest["sources"]:
            if entry["source_identity"] in latest:
                continue
            if stop_after is not None and processed >= stop_after:
                return {"batch": batch, "processed": processed, "imported": imported, "interrupted": True}
            processed += 1
            duplicate = hashes.get(entry["source_hash"])
            if duplicate:
                row = self._row(entry, duplicates=duplicate["imported_ids"])
                self._append(batch, row)
                continue
            raw = (self._batch_dir(batch) / entry["raw_snapshot"]).read_bytes()
            try:
                text = raw.decode("utf-8")
                key = self._contradiction_key(text)
                conflict = contradictions.get(key) if key else None
                request_id = f"migration:{batch}:{entry['source_hash']}:{self._hash(entry['source_identity'].encode())}"
                record = self.service.add(AddRequest(request_id, "fact", "global", text,
                                                        tags=("migration", batch, entry["source_kind"])))
                row = self._row(entry, imported_ids=[str(record.id)],
                                conflicts=[f"review:{conflict['source_identity']}"] if conflict else [],
                                contradiction_key=key)
                self._append(batch, row)
                hashes[entry["source_hash"]] = row
                if key:
                    contradictions[key] = row
                imported += 1
            except (UnicodeDecodeError, OSError, MemoryError) as error:
                self._append(batch, self._row(entry, failures=[type(error).__name__]))
        return {"batch": batch, "processed": processed, "imported": imported, "interrupted": False}

    def _mapped_apps(self) -> set[str]:
        if not self.project_map.is_file():
            return set()
        mapping = json.loads(self.project_map.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict) or not all(isinstance(value, str) for value in mapping.values()):
            raise MemoryError("invalid_request", "project map must map source paths to app ids")
        return set(mapping.values())

    def _hosted_pages(self, pages: list[dict] | None) -> list[dict]:
        if not pages:
            return []
        apps = sorted(self._mapped_apps())
        normalized = []
        for number, page in enumerate(pages):
            if isinstance(page, list):
                if number >= len(apps):
                    raise MemoryError("invalid_request", "hosted page has no mapped app id")
                page = {"app_id": apps[number], "cursor": str(number), "records": page}
            if not isinstance(page, dict) or not isinstance(page.get("app_id"), str) or not isinstance(page.get("records"), list):
                raise MemoryError("invalid_request", "hosted page must include app_id and records")
            if page["app_id"] not in apps:
                raise MemoryError("invalid_request", "hosted app id is not in the project map")
            normalized.append({"app_id": page["app_id"], "cursor": str(page.get("cursor", number)), "records": page["records"]})
        return normalized

    @staticmethod
    def _scope_identity(app_id: str) -> str:
        return f"alex/{app_id}"

    def _hosted_scope_latest(self, rows: list[dict]) -> dict[str, dict]:
        scopes = {}
        for row in rows:
            if row["source_kind"] == "hosted" and row.get("hosted_scope"):
                scopes[row["source_identity"]] = row
            elif row["source_kind"] == "hosted" and row["source_identity"].count("/") == 1:
                scopes[row["source_identity"]] = row
        return scopes

    def import_mem0(self, batch: str, pages: list[dict] | None = None,
                    quota_failure_after_page: int | None = None) -> dict:
        self._manifest(batch)
        rows = self._rows(batch)
        normalized = self._hosted_pages(pages)
        if not normalized:
            deferred_scopes = [row for row in self._hosted_scope_latest(rows).values() if row.get("deferred")]
            if deferred_scopes:
                return {"batch": batch, "imported": 0, "deferred": QUOTA_DEFERRAL, "resume_cursor": deferred_scopes[0]["cursor"]}
            apps = sorted(self._mapped_apps())
            if not apps:
                raise MemoryError("invalid_request", "project map has no hosted app ids")
            entry = {"source_kind": "hosted", "source_identity": self._scope_identity(apps[0]), "source_hash": None, "raw_snapshot": None}
            self._append(batch, self._row(entry, hosted_scope=True, deferred=QUOTA_DEFERRAL))
            return {"batch": batch, "imported": 0, "deferred": QUOTA_DEFERRAL, "resume_cursor": None}
        seen = {(row["source_identity"], row["source_hash"]) for row in rows
                if row["source_kind"] == "hosted" and row.get("source_hash") and row.get("imported_ids")}
        scopes = self._hosted_scope_latest(rows)
        imported = 0
        resume_cursor = None
        for page_number, page in enumerate(normalized):
            raw = json.dumps(page, sort_keys=True, separators=(",", ":")).encode("utf-8")
            snapshot_key = f"{page['app_id']}:{page['cursor']}"
            snapshot = f"hosted/{self._hash(snapshot_key.encode())}.json"
            target = self._batch_dir(batch) / snapshot
            target.parent.mkdir(exist_ok=True)
            if target.exists() and target.read_bytes() != raw:
                raise MemoryError("snapshot_exists", "hosted snapshot differs from the immutable page")
            if not target.exists():
                target.write_bytes(raw)
            for item in page["records"]:
                if not isinstance(item, dict) or "id" not in item:
                    raise MemoryError("invalid_request", "hosted record must have a source-local id")
                identity = f"{self._scope_identity(page['app_id'])}/{item['id']}"
                digest = self._hash(json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                if (identity, digest) in seen:
                    continue
                entry = {"source_kind": "hosted", "source_identity": identity, "source_hash": digest, "raw_snapshot": snapshot}
                record = self.service.add(AddRequest(f"migration:{batch}:hosted:{digest}", "fact", "global",
                                                       str(item.get("memory", "")), tags=("migration", batch, "hosted")))
                self._append(batch, self._row(entry, cursor=page["cursor"], imported_ids=[str(record.id)]))
                seen.add((identity, digest))
                imported += 1
            scope = self._scope_identity(page["app_id"])
            if scopes.get(scope, {}).get("deferred"):
                entry = {"source_kind": "hosted", "source_identity": scope, "source_hash": self._hash(raw), "raw_snapshot": snapshot}
                row = self._row(entry, cursor=page["cursor"], hosted_scope=True)
                self._append(batch, row)
                scopes[scope] = row
            resume_cursor = page["cursor"]
            if quota_failure_after_page is not None and page_number + 1 >= quota_failure_after_page:
                next_page = normalized[page_number + 1] if page_number + 1 < len(normalized) else page
                scope = self._scope_identity(next_page["app_id"])
                existing = scopes.get(scope)
                if not existing or not existing.get("deferred"):
                    entry = {"source_kind": "hosted", "source_identity": scope, "source_hash": None, "raw_snapshot": snapshot}
                    row = self._row(entry, cursor=page["cursor"], hosted_scope=True, deferred=QUOTA_DEFERRAL)
                    self._append(batch, row)
                return {"batch": batch, "imported": imported, "deferred": QUOTA_DEFERRAL, "resume_cursor": resume_cursor}
        return {"batch": batch, "imported": imported, "deferred": None, "resume_cursor": resume_cursor}

    def _summary(self, batch: str) -> dict:
        manifest = self._manifest(batch)
        rows = self._rows(batch)
        latest = self._latest_local(batch)
        unaccounted = [entry for entry in manifest["sources"] if entry["source_identity"] not in latest or not any(
            latest[entry["source_identity"]].get(key) for key in ("imported_ids", "duplicates", "deferred", "waiver"))]
        deferred = [identity for identity, row in self._hosted_scope_latest(rows).items() if row.get("deferred")]
        conflicts = sum(len(row.get("conflicts", [])) for row in latest.values())
        return {"batch": batch, "source_files": len(manifest["sources"]), "ledger_rows": len(rows),
                "unaccounted_sources": len(unaccounted), "deferred_hosted_scopes": deferred,
                "contradictions": conflicts, "local_deferrals": sum(bool(row.get("deferred")) for row in latest.values()),
                "waivers": sum(bool(row.get("waiver")) for row in latest.values()),
                "manifest_hash": self._hash(self._manifest_path(batch).read_bytes())}

    def report(self, batch: str) -> dict:
        summary = self._summary(batch)
        rows = self._rows(batch)
        destination = self.service.store.vault / "Migration" / "report.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Migration Reconciliation Report", "", f"Batch: `{batch}`", "",
                 f"Manifest SHA-256: `{summary['manifest_hash']}`", "",
                 "| Source kind | Source identity | Source hash | Raw snapshot | Raw count | Cursor | Imported IDs | Duplicate IDs | Conflict links | Failures | Deferrals | Waiver reason | Waiver decision |",
                 "| --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for row in rows:
            lines.append("| {source_kind} | {source_identity} | {source_hash} | {raw_snapshot} | {raw_count} | {cursor} | {imported} | {duplicates} | {conflicts} | {failures} | {deferred} | {waiver_reason} | {waiver_decision} |".format(
                source_kind=row["source_kind"], source_identity=row["source_identity"], source_hash=row.get("source_hash") or "-",
                raw_snapshot=row.get("raw_snapshot") or "-", raw_count=row.get("raw_count", 1 if row.get("raw_snapshot") else 0), cursor=row.get("cursor") or "-",
                imported=",".join(row["imported_ids"]) or "-", duplicates=",".join(row["duplicates"]) or "-",
                conflicts=",".join(row["conflicts"]) or "-", deferred=row["deferred"]["reason"] if row["deferred"] else "-",
                failures=",".join(row["failures"]) or "-", waiver_reason=row["waiver"]["reason"] if row["waiver"] else "-",
                waiver_decision=row["waiver"]["decision"] if row["waiver"] else "-"))
        lines.extend(["", f"Source files: {summary['source_files']}", f"Unaccounted sources: {summary['unaccounted_sources']}",
                      f"Contradictions requiring review: {summary['contradictions']}"])
        if summary["deferred_hosted_scopes"]:
            lines.extend(["", "Hosted deferral:", "```json", json.dumps(QUOTA_DEFERRAL, sort_keys=True), "```"])
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return summary

    def verify(self, batch: str) -> dict:
        summary = self._summary(batch)
        for entry in self._manifest(batch)["sources"]:
            snapshot = self._batch_dir(batch) / entry["raw_snapshot"]
            if not snapshot.is_file() or self._hash(snapshot.read_bytes()) != entry["source_hash"]:
                raise MemoryError("verification_failed", "snapshot hash mismatch")
        if summary["unaccounted_sources"]:
            raise MemoryError("verification_failed", "migration has unaccounted sources")
        return {**summary, "verified": True}
