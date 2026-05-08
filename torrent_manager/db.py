from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import EventRecord, TorrentRecord


class Database:
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

                CREATE TABLE IF NOT EXISTS torrents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    download_dir TEXT NOT NULL,
                    torrent_file_path TEXT,
                    info_hash TEXT,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    total_size INTEGER NOT NULL DEFAULT 0,
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    uploaded INTEGER NOT NULL DEFAULT 0,
                    download_rate INTEGER NOT NULL DEFAULT 0,
                    upload_rate INTEGER NOT NULL DEFAULT 0,
                    peers INTEGER NOT NULL DEFAULT 0,
                    seeds INTEGER NOT NULL DEFAULT 0,
                    ratio REAL NOT NULL DEFAULT 0,
                    eta_seconds INTEGER,
                    metadata_ready INTEGER NOT NULL DEFAULT 0,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    resume_data BLOB,
                    error_message TEXT,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    torrent_id TEXT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (torrent_id) REFERENCES torrents(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self.conn.commit()

    def upsert_torrent(self, record: TorrentRecord) -> None:
        payload = record.to_dict()
        payload["metadata_ready"] = 1 if record.metadata_ready else 0
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO torrents (
                    id, name, source_type, source_value, download_dir,
                    torrent_file_path, info_hash, status, progress, total_size,
                    downloaded, uploaded, download_rate, upload_rate, peers,
                    seeds, ratio, eta_seconds, metadata_ready, file_count,
                    resume_data, error_message, added_at, updated_at, completed_at
                ) VALUES (
                    :id, :name, :source_type, :source_value, :download_dir,
                    :torrent_file_path, :info_hash, :status, :progress, :total_size,
                    :downloaded, :uploaded, :download_rate, :upload_rate, :peers,
                    :seeds, :ratio, :eta_seconds, :metadata_ready, :file_count,
                    :resume_data, :error_message, :added_at, :updated_at, :completed_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    source_type = excluded.source_type,
                    source_value = excluded.source_value,
                    download_dir = excluded.download_dir,
                    torrent_file_path = excluded.torrent_file_path,
                    info_hash = excluded.info_hash,
                    status = excluded.status,
                    progress = excluded.progress,
                    total_size = excluded.total_size,
                    downloaded = excluded.downloaded,
                    uploaded = excluded.uploaded,
                    download_rate = excluded.download_rate,
                    upload_rate = excluded.upload_rate,
                    peers = excluded.peers,
                    seeds = excluded.seeds,
                    ratio = excluded.ratio,
                    eta_seconds = excluded.eta_seconds,
                    metadata_ready = excluded.metadata_ready,
                    file_count = excluded.file_count,
                    resume_data = excluded.resume_data,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                payload,
            )
            self.conn.commit()

    def get_torrent(self, torrent_id: str) -> TorrentRecord | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM torrents WHERE id = ?",
                (torrent_id,),
            ).fetchone()
        return self._row_to_torrent(row) if row else None

    def list_torrents(self, include_removed: bool = False) -> list[TorrentRecord]:
        query = "SELECT * FROM torrents"
        params: tuple[object, ...] = ()
        if not include_removed:
            query += " WHERE status != ?"
            params = ("removed",)
        query += " ORDER BY updated_at DESC"
        with self.lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_torrent(row) for row in rows]

    def add_event(self, torrent_id: str | None, level: str, message: str, created_at: str) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO events (torrent_id, level, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (torrent_id, level, message, created_at),
            )
            self.conn.commit()

    def list_events(self, limit: int = 200, torrent_id: str | None = None) -> list[EventRecord]:
        if torrent_id:
            query = """
                SELECT e.id, e.torrent_id, e.level, e.message, e.created_at, t.name AS torrent_name
                FROM events e
                LEFT JOIN torrents t ON t.id = e.torrent_id
                WHERE e.torrent_id = ?
                ORDER BY e.created_at DESC
                LIMIT ?
            """
            params = (torrent_id, limit)
        else:
            query = """
                SELECT e.id, e.torrent_id, e.level, e.message, e.created_at, t.name AS torrent_name
                FROM events e
                LEFT JOIN torrents t ON t.id = e.torrent_id
                ORDER BY e.created_at DESC
                LIMIT ?
            """
            params = (limit,)
        with self.lock:
            rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO settings(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            self.conn.commit()

    def set_default_setting(self, key: str, value: str) -> None:
        if self.get_setting(key) is None:
            self.set_setting(key, value)

    @staticmethod
    def _row_to_torrent(row: sqlite3.Row) -> TorrentRecord:
        return TorrentRecord(
            id=row["id"],
            name=row["name"],
            source_type=row["source_type"],
            source_value=row["source_value"],
            download_dir=row["download_dir"],
            torrent_file_path=row["torrent_file_path"],
            info_hash=row["info_hash"],
            status=row["status"],
            progress=float(row["progress"]),
            total_size=int(row["total_size"]),
            downloaded=int(row["downloaded"]),
            uploaded=int(row["uploaded"]),
            download_rate=int(row["download_rate"]),
            upload_rate=int(row["upload_rate"]),
            peers=int(row["peers"]),
            seeds=int(row["seeds"]),
            ratio=float(row["ratio"]),
            eta_seconds=row["eta_seconds"],
            metadata_ready=bool(row["metadata_ready"]),
            file_count=int(row["file_count"]),
            resume_data=row["resume_data"],
            error_message=row["error_message"],
            added_at=row["added_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=row["id"],
            torrent_id=row["torrent_id"],
            torrent_name=row["torrent_name"],
            level=row["level"],
            message=row["message"],
            created_at=row["created_at"],
        )

