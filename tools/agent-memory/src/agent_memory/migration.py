from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

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
                "source_hash": entry["source_hash"], "cursor": None, "raw_snapshot": entry["raw_snapshot"],
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
            return normalized.replace(" enabled", "").replace(" disabled", "")
        return None

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

    def import_mem0(self, batch: str, pages: list[list[dict]] | None = None,
                    quota_failure_after_page: int | None = None) -> dict:
        self._manifest(batch)
        rows = self._rows(batch)
        if any(row["source_kind"] == "hosted" and row.get("deferred") for row in rows):
            return {"batch": batch, "imported": 0, "deferred": QUOTA_DEFERRAL}
        pages = pages or []
        imported = 0
        for page_number, page in enumerate(pages):
            raw = json.dumps(page, sort_keys=True, separators=(",", ":")).encode("utf-8")
            snapshot = f"hosted/page-{page_number:04d}.json"
            target = self._batch_dir(batch) / snapshot
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                target.write_bytes(raw)
            for item in page:
                identity = f"alex/app-one/{item.get('id', imported)}"
                digest = self._hash(json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                entry = {"source_kind": "hosted", "source_identity": identity, "source_hash": digest,
                         "raw_snapshot": snapshot}
                record = self.service.add(AddRequest(f"migration:{batch}:hosted:{digest}", "fact", "global",
                                                       str(item.get("memory", "")), tags=("migration", batch, "hosted")))
                self._append(batch, self._row(entry, cursor=page_number, imported_ids=[str(record.id)]))
                imported += 1
            if quota_failure_after_page is not None and page_number + 1 >= quota_failure_after_page:
                break
        if not pages or quota_failure_after_page is not None:
            entry = {"source_kind": "hosted", "source_identity": "alex/app-two", "source_hash": None,
                     "raw_snapshot": None}
            self._append(batch, self._row(entry, deferred=QUOTA_DEFERRAL))
            return {"batch": batch, "imported": imported, "deferred": QUOTA_DEFERRAL}
        return {"batch": batch, "imported": imported, "deferred": None}

    def _summary(self, batch: str) -> dict:
        manifest = self._manifest(batch)
        rows = self._rows(batch)
        latest = self._latest_local(batch)
        unaccounted = [entry for entry in manifest["sources"] if entry["source_identity"] not in latest or not any(
            latest[entry["source_identity"]].get(key) for key in ("imported_ids", "duplicates", "deferred", "waiver"))]
        deferred = [row["source_identity"] for row in rows if row["source_kind"] == "hosted" and row.get("deferred")]
        conflicts = sum(len(row.get("conflicts", [])) for row in latest.values())
        return {"batch": batch, "source_files": len(manifest["sources"]), "ledger_rows": len(rows),
                "unaccounted_sources": len(unaccounted), "deferred_hosted_scopes": deferred,
                "contradictions": conflicts, "manifest_hash": self._hash(self._manifest_path(batch).read_bytes())}

    def report(self, batch: str) -> dict:
        summary = self._summary(batch)
        rows = self._rows(batch)
        destination = self.service.store.vault / "Migration" / "report.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Migration Reconciliation Report", "", f"Batch: `{batch}`", "",
                 f"Manifest SHA-256: `{summary['manifest_hash']}`", "",
                 "| Source | Hash | Imported | Duplicates | Conflicts | Deferred | Failures | Waiver |",
                 "| --- | --- | ---: | --- | --- | --- | --- | --- |"]
        for row in rows:
            lines.append("| {source_identity} | {source_hash} | {imported} | {duplicates} | {conflicts} | {deferred} | {failures} | {waiver} |".format(
                source_identity=Path(row["source_identity"]).name, source_hash=row.get("source_hash") or "-",
                imported=len(row["imported_ids"]), duplicates=",".join(row["duplicates"]) or "-",
                conflicts=",".join(row["conflicts"]) or "-", deferred=row["deferred"]["reason"] if row["deferred"] else "-",
                failures=",".join(row["failures"]) or "-", waiver=row["waiver"] or "-"))
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
