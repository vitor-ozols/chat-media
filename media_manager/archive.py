from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from torrent_manager.utils import utc_now

from .config import MediaPaths
from .db import MediaDatabase
from .models import DownloadRecord


class ArchiveService:
    """Download all MP3 files from an Internet Archive item."""

    def __init__(self, paths: MediaPaths, db: MediaDatabase):
        self.paths = paths
        self.db = db
        self.jobs: queue.Queue[str] = queue.Queue()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="archive-downloads")
        self.thread.start()

    @staticmethod
    def identifier(url: str) -> str | None:
        parsed = urlparse(url.strip())
        if parsed.netloc.lower() not in {"archive.org", "www.archive.org"}:
            return None
        match = re.match(r"^/download/([^/?#]+)", parsed.path)
        return unquote(match.group(1)) if match else None

    def enqueue(self, url: str) -> DownloadRecord:
        identifier = self.identifier(url)
        if not identifier:
            raise ValueError("URL do Internet Archive invalida: use /download/IDENTIFICADOR.")
        record = DownloadRecord(
            id=uuid.uuid4().hex,
            source_kind="archive_mp3",
            source_value=url,
            display_name=identifier,
            media_type="music",
            status="queued",
            target_path=str(self.paths.music_dir / identifier),
        )
        self.db.upsert_download(record)
        self.jobs.put(record.id)
        return record

    def _worker_loop(self) -> None:
        while True:
            download_id = self.jobs.get()
            try:
                self._run(download_id)
            finally:
                self.jobs.task_done()

    def _run(self, download_id: str) -> None:
        record = self.db.get_download(download_id)
        if not record:
            return
        try:
            identifier = self.identifier(record.source_value)
            if not identifier:
                raise ValueError("URL do Internet Archive invalida.")
            metadata = self._json(f"https://archive.org/metadata/{quote(identifier, safe='')}")
            files = [item for item in metadata.get("files", []) if self._is_mp3(item)]
            if not files:
                raise RuntimeError("O item nao possui arquivos MP3 publicos.")
            target = Path(record.target_path)
            target.mkdir(parents=True, exist_ok=True)
            details = {"identifier": identifier, "total": len(files), "files": []}
            self.db.upsert_download(record.copy(status="downloading", details_json=json.dumps(details), updated_at=utc_now()))
            for index, item in enumerate(files, start=1):
                name = Path(unquote(str(item.get("name", "")))).name
                if not name:
                    continue
                destination = target / name
                request = Request(
                    f"https://archive.org/download/{quote(identifier, safe='')}/{quote(str(item['name']), safe='/')}",
                    headers={"User-Agent": "chat-media/1.0"},
                )
                with urlopen(request, timeout=60) as response, destination.with_suffix(destination.suffix + ".part").open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                destination.with_suffix(destination.suffix + ".part").replace(destination)
                details["files"].append(name)
                details["current"] = name
                self.db.upsert_download(record.copy(
                    display_name=f"{identifier} ({index}/{len(files)})",
                    status="downloading" if index < len(files) else "completed",
                    progress=index / len(files),
                    details_json=json.dumps(details),
                    updated_at=utc_now(),
                    completed_at=utc_now() if index == len(files) else None,
                ))
        except Exception as exc:
            self.db.upsert_download(record.copy(status="error", error_message=f"Archive.org: {exc}", updated_at=utc_now()))

    @staticmethod
    def _json(url: str) -> dict:
        request = Request(url, headers={"User-Agent": "chat-media/1.0"})
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("resposta invalida da API do Archive.org")
        return payload

    @staticmethod
    def _is_mp3(item: dict) -> bool:
        name = str(item.get("name", ""))
        return name.lower().endswith(".mp3") and not item.get("private")
