from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .model import ListQuery, MemoryRecord, SearchQuery, SearchResult


class MemoryIndex:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, type TEXT NOT NULL, scope TEXT NOT NULL,
                    project TEXT, content TEXT NOT NULL, importance REAL NOT NULL,
                    confidence REAL NOT NULL, pinned INTEGER NOT NULL, tags TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL, content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(id UNINDEXED, content);
                CREATE TABLE IF NOT EXISTS idempotency (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def upsert(self, record: MemoryRecord) -> None:
        values = record.to_dict()
        values["tags"] = ",".join(record.tags)
        values["pinned"] = int(record.pinned)
        with self._connect() as connection:
            connection.execute("""INSERT OR REPLACE INTO memories VALUES
                (:id, :type, :scope, :project, :content, :importance, :confidence, :pinned,
                 :tags, :status, :revision, :content_hash, :created_at, :updated_at)""", values)
            connection.execute("DELETE FROM memories_fts WHERE id = ?", (values["id"],))
            connection.execute("INSERT INTO memories_fts (id, content) VALUES (?, ?)", (values["id"], values["content"]))

    def remove(self, memory_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            connection.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))

    def idempotency(self, request_id: str) -> tuple[str, str] | None:
        with self._connect() as connection:
            return connection.execute("SELECT payload_hash, result_json FROM idempotency WHERE request_id = ?", (request_id,)).fetchone()

    def remember_idempotency(self, request_id: str, payload_hash: str, result: dict) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO idempotency VALUES (?, ?, ?)", (request_id, payload_hash, json.dumps(result, sort_keys=True, separators=(",", ":"))))

    def list(self, query: ListQuery) -> list[MemoryRecord]:
        clauses, values = [], []
        for name in ("project", "scope", "type", "status"):
            value = getattr(query, name)
            if value is not None:
                clauses.append(f"{name} = ?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memories" + where + " ORDER BY created_at, id", values).fetchall()
        return [self._record(row) for row in rows]

    def search_lexical(self, query: SearchQuery) -> SearchResult:
        terms = re.findall(r"[\w]+", query.query, flags=re.UNICODE)
        if not terms:
            return SearchResult([])
        sql = "SELECT m.* FROM memories_fts f JOIN memories m ON m.id = f.id WHERE memories_fts MATCH ?"
        values = [" AND ".join(f'"{term}"' for term in terms)]
        if query.project is not None:
            sql += " AND m.project = ?"
            values.append(query.project)
        if query.status is not None:
            sql += " AND m.status = ?"
            values.append(query.status)
        sql += " ORDER BY bm25(memories_fts), m.id"
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return SearchResult([self._record(row) for row in rows])

    @staticmethod
    def _record(row: tuple) -> MemoryRecord:
        from uuid import UUID
        return MemoryRecord(UUID(row[0]), row[1], row[2], row[3], row[4], row[5], row[6], bool(row[7]), tuple(filter(None, row[8].split(","))), row[9], row[10], row[11], row[12], row[13])
