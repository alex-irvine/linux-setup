from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from .model import ListQuery, MemoryRecord, SearchQuery, SearchResult


RECORD_COLUMNS = "id, type, scope, project, content, importance, confidence, pinned, tags, status, revision, content_hash, created_at, updated_at"


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
                     created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                     externally_modified INTEGER NOT NULL DEFAULT 0
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(id UNINDEXED, content);
                CREATE TABLE IF NOT EXISTS idempotency (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY, positive INTEGER NOT NULL DEFAULT 0, negative INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS excluded_paths (path TEXT PRIMARY KEY, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS admin_operations (
                    request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS embeddings (id TEXT PRIMARY KEY, vector TEXT NOT NULL);
            """)
            self._migrate(connection)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        memory_columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
        if "status" not in memory_columns:
            connection.execute("ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "externally_modified" not in memory_columns:
            connection.execute("ALTER TABLE memories ADD COLUMN externally_modified INTEGER NOT NULL DEFAULT 0")
        idempotency_columns = {row[1] for row in connection.execute("PRAGMA table_info(idempotency)")}
        if "result_id" in idempotency_columns:
            connection.execute("ALTER TABLE idempotency RENAME TO legacy_idempotency")
            connection.execute("""CREATE TABLE idempotency (
                request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL
            )""")
            for request_id, payload_hash, result_id in connection.execute("SELECT request_id, payload_hash, result_id FROM legacy_idempotency"):
                row = connection.execute(f"SELECT {RECORD_COLUMNS} FROM memories WHERE id = ?", (result_id,)).fetchone()
                if row is not None:
                    result = self._record(row).to_dict()
                    connection.execute("INSERT INTO idempotency VALUES (?, ?, ?)", (request_id, payload_hash, json.dumps(result, sort_keys=True, separators=(",", ":"))))
            connection.execute("DROP TABLE legacy_idempotency")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def upsert(self, record: MemoryRecord, externally_modified: bool = False) -> None:
        values = record.to_dict()
        values["tags"] = ",".join(record.tags)
        values["pinned"] = int(record.pinned)
        with self._connect() as connection:
            connection.execute("""INSERT OR REPLACE INTO memories
                (id, type, scope, project, content, importance, confidence, pinned, tags,
                  status, revision, content_hash, created_at, updated_at)
                VALUES (:id, :type, :scope, :project, :content, :importance, :confidence,
                        :pinned, :tags, :status, :revision, :content_hash, :created_at,
                         :updated_at)""", values)
            connection.execute("UPDATE memories SET externally_modified = ? WHERE id = ?", (int(externally_modified), values["id"]))
            connection.execute("DELETE FROM memories_fts WHERE id = ?", (values["id"],))
            connection.execute("INSERT INTO memories_fts (id, content) VALUES (?, ?)", (values["id"], values["content"]))

    def remove(self, memory_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            connection.execute("DELETE FROM memories_fts WHERE id = ?", (memory_id,))
            connection.execute("DELETE FROM feedback WHERE id = ?", (memory_id,))

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM memories")
            connection.execute("DELETE FROM memories_fts")
            connection.execute("DELETE FROM excluded_paths")
            connection.execute("DELETE FROM embeddings")

    def remember_embeddings(self, records: list[MemoryRecord], vectors: list[list[float]]) -> None:
        with self._connect() as connection:
            connection.executemany("INSERT OR REPLACE INTO embeddings VALUES (?, ?)",
                                   [(str(record.id), json.dumps(vector, separators=(",", ":")))
                                    for record, vector in zip(records, vectors)])

    def exclude_path(self, path: Path, reason: str = "invalid memory frontmatter") -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO excluded_paths VALUES (?, ?)", (str(path), reason))

    def excluded_paths(self) -> list[str]:
        with self._connect() as connection:
            return [row[0] for row in connection.execute("SELECT path FROM excluded_paths ORDER BY path")]

    def feedback(self, memory_id: str, rating: str) -> dict:
        column = "positive" if rating == "positive" else "negative"
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO feedback (id) VALUES (?)", (memory_id,))
            connection.execute(f"UPDATE feedback SET {column} = {column} + 1 WHERE id = ?", (memory_id,))
            positive, negative = connection.execute("SELECT positive, negative FROM feedback WHERE id = ?", (memory_id,)).fetchone()
        return {"id": memory_id, "positive": positive, "negative": negative}

    def feedback_counts(self, memory_id: str) -> tuple[int, int]:
        with self._connect() as connection:
            row = connection.execute("SELECT positive, negative FROM feedback WHERE id = ?", (memory_id,)).fetchone()
        return row or (0, 0)

    def set_feedback(self, memory_id: str, positive: int, negative: int) -> None:
        with self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO feedback VALUES (?, ?, ?)", (memory_id, positive, negative))

    def admin_operation(self, request_id: str) -> tuple[str, str] | None:
        with self._connect() as connection:
            return connection.execute("SELECT payload_hash, result_json FROM admin_operations WHERE request_id = ?", (request_id,)).fetchone()

    def remember_admin_operation(self, request_id: str, payload_hash: str, result: dict) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO admin_operations VALUES (?, ?, ?)", (request_id, payload_hash, json.dumps(result, sort_keys=True)))

    def idempotency(self, request_id: str) -> tuple[str, str] | None:
        with self._connect() as connection:
            return connection.execute("SELECT payload_hash, result_json FROM idempotency WHERE request_id = ? AND result_json IS NOT NULL", (request_id,)).fetchone()

    def remember_idempotency(self, request_id: str, payload_hash: str, result: dict) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO idempotency (request_id, payload_hash, result_json) VALUES (?, ?, ?)", (request_id, payload_hash, json.dumps(result, sort_keys=True, separators=(",", ":"))))

    def list(self, query: ListQuery) -> list[MemoryRecord]:
        clauses, values = [], []
        for name in ("project", "scope", "type", "status"):
            value = getattr(query, name)
            if value is not None:
                clauses.append(f"{name} = ?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(f"SELECT {RECORD_COLUMNS} FROM memories" + where + " ORDER BY created_at, id", values).fetchall()
        return [self._record(row) for row in rows]

    def search_lexical(self, query: SearchQuery) -> SearchResult:
        terms = re.findall(r"[\w]+", query.query, flags=re.UNICODE)
        if not terms:
            return SearchResult([])
        sql = f"SELECT {','.join(f'm.{column.strip()}' for column in RECORD_COLUMNS.split(','))} FROM memories_fts f JOIN memories m ON m.id = f.id WHERE memories_fts MATCH ?"
        values = [" AND ".join(f'"{term}"' for term in terms)]
        if query.project is not None:
            sql += " AND m.project = ?"
            values.append(query.project)
        if query.status is not None:
            sql += " AND m.status = ?"
            values.append(query.status)
        if query.scope is not None:
            sql += " AND m.scope = ?"
            values.append(query.scope)
        if query.type is not None:
            sql += " AND m.type = ?"
            values.append(query.type)
        for tag in query.tags:
            sql += " AND instr(',' || m.tags || ',', ',' || ? || ',') > 0"
            values.append(tag)
        sql += " ORDER BY bm25(memories_fts), m.id"
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return SearchResult([self._record(row).to_dict() for row in rows])

    def candidates(self, query: SearchQuery) -> list[MemoryRecord]:
        return [record for record in self.list(ListQuery(query.project, query.scope, query.type, query.status))
                if set(query.tags).issubset(record.tags)]

    @staticmethod
    def _record(row: tuple) -> MemoryRecord:
        from uuid import UUID
        return MemoryRecord(UUID(row[0]), row[1], row[2], row[3], row[4], row[5], row[6], bool(row[7]), tuple(filter(None, row[8].split(","))), row[9], row[10], row[11], row[12], row[13])
