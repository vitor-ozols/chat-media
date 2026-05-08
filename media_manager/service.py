from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import streamlit as st

from torrent_manager.config import ensure_app_paths
from torrent_manager.models import TorrentRecord
from torrent_manager.service import TorrentService
from torrent_manager.utils import utc_now

from .classifier import classify_media
from .config import MediaPaths, ensure_media_paths
from .db import MediaDatabase
from .gemini import DEFAULT_MODEL, generate_reply, list_model_choices
from .models import DownloadRecord
from .youtube import YouTubeService


class MediaService:
    def __init__(self, root: Path):
        self.paths: MediaPaths = ensure_media_paths(root)
        self.db = MediaDatabase(self.paths.db_path)
        self.youtube = YouTubeService(self.paths, self.db)
        self.torrent_service = TorrentService(ensure_app_paths(root))

    def list_chat_messages(self) -> list[dict[str, str | None]]:
        return [
            {"role": item.role, "content": item.content, "model": item.model}
            for item in self.db.list_chat_messages()
        ]

    def add_chat_message(self, role: str, content: str, model: str | None = None) -> None:
        self.db.add_chat_message(role=role, content=content, model=model)

    def get_model_choices(self, api_key: str | None = None) -> list[str]:
        return list_model_choices(api_key)

    def enqueue_youtube(self, url: str, metadata: dict[str, str] | None = None) -> DownloadRecord:
        return self.youtube.enqueue(url, metadata=metadata)

    def retry_youtube_download(self, download_id: str) -> DownloadRecord | None:
        record = self.db.get_download(download_id)
        if record is None:
            return None
        details = self._load_download_details(record)
        metadata = details.get("metadata", {})
        if record.source_kind in {"youtube", "youtube_playlist"}:
            return self.youtube.enqueue(record.source_value, metadata=metadata)
        return None

    def add_torrent_from_magnet(self, magnet: str, api_key: str | None = None, model: str | None = None) -> TorrentRecord:
        name = self._extract_magnet_name(magnet) or magnet
        media_type = classify_media(name, api_key=api_key, model=model)
        target_dir = self.paths.music_dir if media_type == "music" else self.paths.movies_dir
        record = self.torrent_service.add_magnets([magnet], download_dir=str(target_dir))[0]
        self._sync_torrent_to_download(record, media_type)
        return record

    def add_torrent_file(
        self,
        filename: str,
        payload: bytes,
        api_key: str | None = None,
        model: str | None = None,
    ) -> TorrentRecord:
        media_type = classify_media(filename, api_key=api_key, model=model)
        target_dir = self.paths.music_dir if media_type == "music" else self.paths.movies_dir
        record = self.torrent_service.add_torrent_file(
            filename=filename,
            payload=payload,
            download_dir=str(target_dir),
        )
        inferred_media_type = classify_media(record.name or filename, api_key=api_key, model=model)
        self._sync_torrent_to_download(record, inferred_media_type)
        return record

    def sync_downloads(self) -> None:
        for record in self.torrent_service.list_torrents(include_removed=True):
            if record.status == "removed":
                existing = self._find_download_by_external_id(record.id)
                if existing:
                    self.db.delete_download(existing.id)
                continue
            existing = self._find_download_by_external_id(record.id)
            media_type = existing.media_type if existing else classify_media(record.name)
            self._sync_torrent_to_download(record, media_type)

    def list_downloads(self) -> list[DownloadRecord]:
        self.sync_downloads()
        self._sync_playlist_records()
        return self.db.list_downloads()

    def clear_chat(self) -> None:
        self.db.clear_chat_messages()

    def clear_download_history(self, stop_torrents: bool = True) -> int:
        stopped = 0
        if stop_torrents:
            for record in self.torrent_service.list_torrents(include_removed=True):
                if record.status != "removed":
                    self.torrent_service.remove_torrent(record.id, delete_files=False)
                    stopped += 1
        self.db.clear_downloads()
        return stopped

    def delete_download(self, download_id: str, stop_torrent: bool = True) -> bool:
        record = self.db.get_download(download_id)
        if record is None:
            return False
        if stop_torrent and record.source_kind == "torrent" and record.external_id:
            self.torrent_service.remove_torrent(record.external_id, delete_files=False)
        self.db.delete_download(download_id)
        return True

    def summarize_download_status(self, limit: int = 5) -> str:
        downloads = self.list_downloads()[:limit]
        if not downloads:
            return "Ainda nao encontrei downloads na fila ou no historico."

        lines = ["Status dos downloads mais recentes:"]
        for item in downloads:
            percent = f"{item.progress * 100:.1f}%"
            if item.status in {"completed", "seeding"} or item.progress >= 1:
                state = "concluido"
            elif item.status == "needs_info":
                state = "aguardando artista e album"
            elif item.status == "error":
                state = "com erro"
            else:
                state = "em andamento"
            lines.append(f"- {item.display_name}: {state} ({percent}) em `{item.target_path}`")
        return "\n".join(lines)

    def build_chat_reply(self, model: str, api_key: str | None = None, action_summary: str | None = None) -> str:
        messages = self.list_chat_messages()
        system_instruction = (
            "Voce e um assistente de gerenciamento de midia em Streamlit. "
            "Responda em portugues do Brasil. Seja curto, pratico e mencione onde os arquivos serao salvos. "
            "Quando houver uma acao local executada, confirme o resultado e nao invente downloads."
        )
        prompt_payload = messages[-8:]
        if action_summary:
            prompt_payload = prompt_payload + [
                {
                    "role": "user",
                    "content": f"Contexto de sistema sobre a ultima acao local:\n{action_summary}",
                    "model": None,
                }
            ]
        return generate_reply(prompt_payload, model=model or DEFAULT_MODEL, api_key=api_key, system_instruction=system_instruction)

    def handle_chat_submission(
        self,
        prompt: str,
        uploaded_torrents: list[tuple[str, bytes]],
        model: str,
        api_key: str | None = None,
    ) -> str:
        prompt = prompt.strip()
        if not prompt:
            prompt = "Processe os arquivos .torrent anexados."
        self.add_chat_message("user", prompt, model=None)
        action_notes: list[str] = []

        youtube_urls = self._extract_youtube_urls(prompt)
        magnets = self._extract_magnets(prompt)
        metadata = self._extract_music_metadata(prompt)

        if not youtube_urls and not magnets and not uploaded_torrents:
            if self._looks_like_status_question(prompt):
                reply = self.summarize_download_status()
                self.add_chat_message("assistant", reply, model=model)
                return reply

            pending = self._latest_pending_youtube_info()
            if pending:
                if metadata.get("artist") and metadata.get("album"):
                    resumed = self.youtube.resume_with_metadata(pending.id, metadata)
                    reply = (
                        "Perfeito, atualizei os metadados e coloquei a musica de volta na fila. "
                        f"Ela sera organizada em `{self.paths.music_dir / metadata['artist'] / metadata['album']}`. "
                        "Acompanhe o progresso na aba Downloads."
                    )
                    if resumed is None:
                        reply = "Nao consegui encontrar a musica pendente para retomar."
                    self.add_chat_message("assistant", reply, model=model)
                    return reply
                reply = (
                    "Preciso dessas informacoes para organizar a musica. "
                    "Me envie no formato: `artista: Nome, album: Nome, musica: Nome`."
                )
                self.add_chat_message("assistant", reply, model=model)
                return reply

        for url in youtube_urls:
            job = self.enqueue_youtube(url, metadata=metadata)
            if job.source_kind == "youtube_playlist":
                action_notes.append(
                    f"Playlist adicionada a fila: {job.display_name} -> {job.target_path}. "
                    "Vou baixar as faixas individualmente e organizar como album."
                )
            else:
                action_notes.append(
                    f"YouTube adicionado a fila: {url} -> {job.target_path}. "
                    "Se faltar artista ou album, eu vou pausar e pedir esses dados antes de baixar."
                )

        for magnet in magnets:
            torrent = self.add_torrent_from_magnet(magnet, api_key=api_key, model=model)
            action_notes.append(f"Torrent magnet: {torrent.name} -> {torrent.download_dir} [{torrent.status}]")

        for filename, payload in uploaded_torrents:
            torrent = self.add_torrent_file(filename, payload, api_key=api_key, model=model)
            action_notes.append(f"Arquivo .torrent: {torrent.name} -> {torrent.download_dir} [{torrent.status}]")

        if action_notes:
            reply = (
                "\n".join(action_notes)
                + "\n\nColoquei na fila de downloads. Acompanhe o progresso na aba Downloads."
            )
        else:
            action_summary = self.summarize_download_status()
            reply = self.build_chat_reply(model=model, api_key=api_key, action_summary=action_summary)
        self.add_chat_message("assistant", reply, model=model)
        return reply

    def _find_download_by_external_id(self, external_id: str) -> DownloadRecord | None:
        for item in self.db.list_downloads(limit=500):
            if item.external_id == external_id:
                return item
        return None

    def _sync_torrent_to_download(self, record: TorrentRecord, media_type: str) -> None:
        existing = self._find_download_by_external_id(record.id)
        download_id = existing.id if existing else uuid.uuid4().hex
        payload = DownloadRecord(
            id=download_id,
            source_kind="torrent",
            source_value=record.source_value,
            display_name=record.name,
            media_type=media_type,
            status=record.status,
            target_path=record.download_dir,
            external_id=record.id,
            progress=record.progress,
            details_json=json.dumps(
                {
                    "info_hash": record.info_hash,
                    "peers": record.peers,
                    "seeds": record.seeds,
                    "download_rate": record.download_rate,
                }
            ),
            error_message=record.error_message,
            created_at=existing.created_at if existing else record.added_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )
        self.db.upsert_download(payload)

    def _sync_playlist_records(self) -> None:
        records = self.db.list_downloads(limit=1000)
        by_id = {item.id: item for item in records}
        for playlist in records:
            if playlist.source_kind != "youtube_playlist":
                continue
            try:
                details = json.loads(playlist.details_json or "{}")
            except Exception:
                continue
            child_ids = [child.get("id") for child in details.get("children", []) if child.get("id")]
            children = [by_id[child_id] for child_id in child_ids if child_id in by_id]
            if not children:
                continue
            progress = sum(child.progress for child in children) / len(children)
            if all(child.status == "completed" or child.progress >= 1 for child in children):
                status = "completed"
            elif any(child.status == "needs_info" for child in children):
                status = "needs_info"
            elif any(child.status == "error" for child in children):
                status = "error"
            else:
                status = "downloading"
            if playlist.status != status or abs(playlist.progress - progress) > 0.001:
                self.db.upsert_download(
                    playlist.copy(
                        status=status,
                        progress=progress,
                        updated_at=utc_now(),
                        completed_at=utc_now() if status == "completed" and not playlist.completed_at else playlist.completed_at,
                    )
                )

    @staticmethod
    def _load_download_details(record: DownloadRecord) -> dict:
        try:
            payload = json.loads(record.details_json or "{}")
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _extract_youtube_urls(text: str) -> list[str]:
        pattern = r"(https?://(?:www\.)?(?:youtube\.com/(?:watch|playlist)\?[^\s]+|youtu\.be/[^\s]+))"
        return [url.rstrip(".,);]") for url in re.findall(pattern, text or "")]

    @staticmethod
    def _extract_magnets(text: str) -> list[str]:
        return re.findall(r"(magnet:\?[^\s]+)", text or "")

    @staticmethod
    def _extract_magnet_name(magnet: str) -> str | None:
        try:
            parsed = urlparse(magnet)
            query = parse_qs(parsed.query)
            return unquote(query.get("dn", [None])[0]) if query.get("dn") else None
        except Exception:
            return None

    def _latest_pending_youtube_info(self) -> DownloadRecord | None:
        for item in self.db.list_downloads(limit=20):
            if item.source_kind == "youtube" and item.status == "needs_info":
                return item
        return None

    @staticmethod
    def _looks_like_status_question(prompt: str) -> bool:
        normalized = prompt.lower()
        terms = ("terminou", "baixou", "acabou", "status", "andamento", "download")
        return any(term in normalized for term in terms)

    @staticmethod
    def _extract_music_metadata(prompt: str) -> dict[str, str]:
        metadata: dict[str, str] = {}
        patterns = {
            "artist": r"(?:artista|artist)\s*[:=]\s*([^,\n]+)",
            "album": r"(?:album|álbum)\s*[:=]\s*([^,\n]+)",
            "title": r"(?:musica|música|titulo|título|track|song)\s*[:=]\s*([^,\n]+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                metadata[key] = match.group(1).strip()
        return metadata


@st.cache_resource(show_spinner=False)
def get_media_service() -> MediaService:
    return MediaService(Path.cwd())
