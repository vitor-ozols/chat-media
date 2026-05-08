from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import ChatMessageRecord, DownloadRecord


class MediaDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = NORMAL;

                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    external_id TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self.conn.commit()

    def upsert_download(self, record: DownloadRecord) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO downloads (
                    id, source_kind, source_value, display_name, media_type,
                    status, target_path, external_id, progress, details_json,
                    error_message, created_at, updated_at, completed_at
                ) VALUES (
                    :id, :source_kind, :source_value, :display_name, :media_type,
                    :status, :target_path, :external_id, :progress, :details_json,
                    :error_message, :created_at, :updated_at, :completed_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    source_value = excluded.source_value,
                    display_name = excluded.display_name,
                    media_type = excluded.media_type,
                    status = excluded.status,
                    target_path = excluded.target_path,
                    external_id = excluded.external_id,
                    progress = excluded.progress,
                    details_json = excluded.details_json,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                record.to_dict(),
            )
            self.conn.commit()

    def get_download(self, download_id: str) -> DownloadRecord | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM downloads WHERE id = ?", (download_id,)).fetchone()
        return self._row_to_download(row) if row else None

    def list_downloads(self, limit: int = 200) -> list[DownloadRecord]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM downloads ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_download(row) for row in rows]

    def clear_downloads(self) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM downloads")
            self.conn.commit()

    def delete_download(self, download_id: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
            self.conn.commit()

    def add_chat_message(self, role: str, content: str, model: str | None = None) -> ChatMessageRecord:
        with self.lock:
            cursor = self.conn.execute(
                """
                INSERT INTO chat_messages (role, content, model, created_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (role, content, model),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM chat_messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return self._row_to_chat(row)

    def list_chat_messages(self, limit: int = 100) -> list[ChatMessageRecord]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_chat(row) for row in reversed(rows)]

    def clear_chat_messages(self) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM chat_messages")
            self.conn.commit()

    @staticmethod
    def _row_to_download(row: sqlite3.Row) -> DownloadRecord:
        return DownloadRecord(
            id=row["id"],
            source_kind=row["source_kind"],
            source_value=row["source_value"],
            display_name=row["display_name"],
            media_type=row["media_type"],
            status=row["status"],
            target_path=row["target_path"],
            external_id=row["external_id"],
            progress=float(row["progress"]),
            details_json=row["details_json"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _row_to_chat(row: sqlite3.Row) -> ChatMessageRecord:
        return ChatMessageRecord(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            model=row["model"],
            created_at=row["created_at"],
        )
