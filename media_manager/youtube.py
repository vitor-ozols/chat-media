from __future__ import annotations

import json
import queue
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from torrent_manager.utils import utc_now

from .config import MediaPaths
from .db import MediaDatabase
from .models import DownloadRecord


class YouTubeService:
    def __init__(self, paths: MediaPaths, db: MediaDatabase):
        self.paths = paths
        self.db = db
        self.jobs: queue.Queue[str] = queue.Queue()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True, name="youtube-downloads")
        self.thread.start()

    def enqueue(
        self,
        url: str,
        metadata: dict[str, str] | None = None,
        treat_as_playlist: bool = False,
        final_path: str | None = None,
    ) -> DownloadRecord:
        if treat_as_playlist:
            return self._enqueue_playlist(url, metadata=metadata, final_path=final_path)
        return self._create_video_job(url, metadata=metadata, final_path=final_path)

    def _create_video_job(
        self,
        url: str,
        metadata: dict[str, str] | None = None,
        parent_id: str | None = None,
        final_path: str | None = None,
    ) -> DownloadRecord:
        download_id = uuid.uuid4().hex
        details = {"metadata": metadata or {}, "parent_id": parent_id, "final_path": final_path}
        record = DownloadRecord(
            id=download_id,
            source_kind="youtube",
            source_value=url,
            display_name=url,
            media_type="music",
            status="queued",
            target_path=final_path or str(self.paths.music_dir),
            details_json=json.dumps(details),
        )
        self.db.upsert_download(record)
        self.jobs.put(download_id)
        return record

    def _enqueue_playlist(
        self,
        url: str,
        metadata: dict[str, str] | None = None,
        final_path: str | None = None,
    ) -> DownloadRecord:
        playlist_url = self._playlist_url(url) or url
        download_id = uuid.uuid4().hex
        details = {"metadata": metadata or {}, "children": [], "final_path": final_path}
        playlist_record = DownloadRecord(
            id=download_id,
            source_kind="youtube_playlist",
            source_value=playlist_url,
            display_name=playlist_url,
            media_type="music",
            status="expanding",
            target_path=final_path or str(self.paths.music_dir),
            details_json=json.dumps(details),
        )
        self.db.upsert_download(playlist_record)

        try:
            import yt_dlp

            options = {
                "extract_flat": "in_playlist",
                "ignoreerrors": True,
                "skip_download": True,
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
        except Exception as exc:
            self.db.upsert_download(
                playlist_record.copy(
                    status="error",
                    error_message=f"Falha ao ler playlist: {exc}",
                    updated_at=utc_now(),
                )
            )
            return playlist_record

        if not info or not isinstance(info, dict):
            self.db.upsert_download(
                playlist_record.copy(
                    status="error",
                    error_message="Nao consegui ler os dados da playlist.",
                    updated_at=utc_now(),
                )
            )
            return playlist_record

        playlist_title = info.get("title") or "Playlist"
        resolved_metadata = {**(metadata or {})}
        if not resolved_metadata.get("album"):
            resolved_metadata["album"] = playlist_title

        children = []
        for entry in info.get("entries") or []:
            if not entry:
                continue
            entry_url = entry.get("webpage_url") or entry.get("url") or entry.get("id")
            if not entry_url:
                continue
            child_url = self._normalize_video_url(entry_url)
            child_metadata = {**resolved_metadata}
            if entry.get("title") and not child_metadata.get("title"):
                child_metadata["title"] = entry["title"]
            child = self._create_video_job(
                child_url,
                metadata=child_metadata,
                parent_id=download_id,
                final_path=final_path,
            )
            children.append({"id": child.id, "title": child.display_name, "url": child_url})

        status = "queued" if children else "error"
        error = None if children else (
            "A playlist nao retornou videos validos. "
            "Confira se ela e publica e tente atualizar o yt-dlp no container."
        )
        self.db.upsert_download(
            playlist_record.copy(
                display_name=playlist_title,
                status=status,
                details_json=json.dumps({"metadata": resolved_metadata, "children": children}),
                error_message=error,
                updated_at=utc_now(),
            )
        )
        return playlist_record

    def resume_with_metadata(self, download_id: str, metadata: dict[str, str]) -> DownloadRecord | None:
        record = self.db.get_download(download_id)
        if record is None:
            return None
        details = self._load_details(record)
        details["metadata"] = {**details.get("metadata", {}), **metadata}
        updated = record.copy(
            status="queued",
            details_json=json.dumps(details),
            error_message=None,
            updated_at=utc_now(),
        )
        self.db.upsert_download(updated)
        self.jobs.put(download_id)
        return updated

    def _worker_loop(self) -> None:
        while True:
            download_id = self.jobs.get()
            try:
                self._run_job(download_id)
            finally:
                self.jobs.task_done()

    def _run_job(self, download_id: str) -> None:
        record = self.db.get_download(download_id)
        if record is None:
            return

        try:
            import yt_dlp
        except Exception as exc:
            self.db.upsert_download(
                record.copy(
                    status="error",
                    error_message=f"`yt-dlp` indisponivel: {exc}",
                    updated_at=utc_now(),
                )
            )
            return

        details = self._load_details(record)
        override_metadata = details.get("metadata", {})
        requested_path = details.get("final_path")
        ffmpeg_available = shutil.which("ffmpeg") is not None

        def progress_hook(payload: dict) -> None:
            local_record = self.db.get_download(download_id)
            if local_record is None:
                return
            filename = payload.get("filename") or local_record.display_name
            status = payload.get("status", "downloading")
            downloaded = payload.get("downloaded_bytes") or 0
            total = payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0
            progress = float(downloaded / total) if total else local_record.progress
            mapped_status = "downloading" if status == "downloading" else status
            current_details = self._load_details(local_record)
            current_details["progress"] = {
                key: payload.get(key)
                for key in ("status", "downloaded_bytes", "total_bytes", "total_bytes_estimate", "speed", "eta")
                if key in payload
            }
            self.db.upsert_download(
                local_record.copy(
                    display_name=Path(filename).name,
                    progress=min(max(progress, 0.0), 1.0),
                    status=mapped_status,
                    details_json=json.dumps(current_details, default=str),
                    updated_at=utc_now(),
                )
            )

        options = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
        }
        if ffmpeg_available:
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        self.db.upsert_download(record.copy(status="downloading", updated_at=utc_now()))
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(record.source_value, download=False)
                if not info or not isinstance(info, dict):
                    self.db.upsert_download(
                        record.copy(
                            status="error",
                            error_message="Nao consegui ler os metadados do video.",
                            updated_at=utc_now(),
                        )
                    )
                    return
                metadata = self._resolve_metadata(info, override_metadata)
                missing = [] if requested_path else [field for field in ("artist", "album") if not metadata.get(field)]
                if missing:
                    details["metadata"] = metadata
                    details["metadata_request_sent"] = True
                    message = self._build_metadata_request_message(record, metadata, missing)
                    self.db.upsert_download(
                        record.copy(
                            display_name=info.get("title") or record.display_name,
                            status="needs_info",
                            progress=0.0,
                            details_json=json.dumps(details, default=str),
                            error_message=(
                                "Preciso do artista e do album para organizar em "
                                "`nome artista/nome album/nome musica`."
                            ),
                            updated_at=utc_now(),
                        )
                    )
                    if not self._load_details(record).get("metadata_request_sent"):
                        self.db.add_chat_message("assistant", message, model=None)
                    return

                requested = Path(requested_path).expanduser() if requested_path else None
                if requested and requested.suffix:
                    target_dir = requested.parent
                    title = self._sanitize(requested.stem)
                elif requested:
                    target_dir = requested
                    title = self._sanitize(metadata.get("title") or info.get("title") or "audio")
                else:
                    target_dir = self.paths.music_dir / self._sanitize(metadata["artist"]) / self._sanitize(metadata["album"])
                    title = self._sanitize(metadata.get("title") or info.get("title") or "musica")
                target_dir.mkdir(parents=True, exist_ok=True)
                ydl.params["outtmpl"] = {"default": str(target_dir / f"{title}.%(ext)s")}
                info = ydl.extract_info(record.source_value, download=True)
                final_name = ydl.prepare_filename(info)
                if ffmpeg_available:
                    final_name = str(Path(final_name).with_suffix(".mp3"))
                details["metadata"] = metadata
                self.db.upsert_download(
                    record.copy(
                        display_name=metadata.get("title") or info.get("title") or Path(final_name).name,
                        progress=1.0,
                        status="completed",
                        target_path=final_name,
                        details_json=json.dumps(
                            {
                                **details,
                                "title": info.get("title"),
                                "extractor": info.get("extractor"),
                                "webpage_url": info.get("webpage_url"),
                            }
                        ),
                        updated_at=utc_now(),
                        completed_at=utc_now(),
                    )
                )
        except Exception as exc:
            self.db.upsert_download(
                record.copy(
                    status="error",
                    error_message=str(exc),
                    updated_at=utc_now(),
                )
            )

    @staticmethod
    def _load_details(record: DownloadRecord) -> dict[str, Any]:
        try:
            payload = json.loads(record.details_json or "{}")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _resolve_metadata(info: dict[str, Any], overrides: dict[str, str]) -> dict[str, str]:
        metadata = {
            "artist": overrides.get("artist") or info.get("artist") or "",
            "album": overrides.get("album") or info.get("album") or "",
            "title": overrides.get("title") or info.get("track") or info.get("title") or "",
        }
        inferred = YouTubeService._infer_artist_title(metadata["title"])
        if inferred:
            artist, title = inferred
            metadata["artist"] = metadata["artist"] or artist
            metadata["title"] = overrides.get("title") or info.get("track") or title
        return metadata

    @staticmethod
    def _sanitize(value: str) -> str:
        cleaned = "".join(char for char in value.strip() if char not in '<>:"/\\|?*')
        return cleaned.strip(" .") or "Desconhecido"

    @staticmethod
    def is_explicit_playlist_url(url: str) -> bool:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        has_playlist_id = bool(query.get("list"))
        return has_playlist_id and "playlist" in parsed.path.lower()

    @staticmethod
    def _normalize_video_url(url: str) -> str:
        if url.startswith("http"):
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            video_id = query.get("v", [None])[0]
            if video_id:
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode({"v": video_id}), ""))
            return url
        return f"https://www.youtube.com/watch?v={url}"

    @staticmethod
    def _playlist_url(url: str) -> str | None:
        parsed = urlparse(url)
        playlist_id = parse_qs(parsed.query).get("list", [None])[0]
        if not playlist_id:
            return None
        return f"https://www.youtube.com/playlist?{urlencode({'list': playlist_id})}"

    @staticmethod
    def _infer_artist_title(title: str) -> tuple[str, str] | None:
        for separator in (" - ", " – ", " — "):
            if separator in title:
                artist, track = title.split(separator, 1)
                artist = artist.strip()
                track = track.strip()
                if artist and track:
                    return artist, track
        return None

    @staticmethod
    def _build_metadata_request_message(
        record: DownloadRecord,
        metadata: dict[str, str],
        missing: list[str],
    ) -> str:
        known = []
        if metadata.get("artist"):
            known.append(f"artista: `{metadata['artist']}`")
        if metadata.get("title"):
            known.append(f"musica: `{metadata['title']}`")
        known_text = f" Eu consegui inferir {', '.join(known)}." if known else ""
        missing_labels = {
            "artist": "artista",
            "album": "album",
        }
        missing_text = " e ".join(missing_labels[field] for field in missing)
        return (
            f"Preciso de {missing_text} para organizar `{record.display_name}` em "
            "`artista/album/musica`." + known_text + "\n\n"
            "Responda aqui no chat, por exemplo: `album: Nome do album` ou "
            "`artista: Nome, album: Nome`."
        )
