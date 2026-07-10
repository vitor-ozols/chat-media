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
from .codex_runtime import CodexRuntime
from .codex_sdk import CodexAuthError, CodexSDK, CodexSetupError
from .db import MediaDatabase
from .models import ChatSessionRecord, DownloadRecord
from .skills import render_skills
from .youtube import YouTubeService


POINTBOT_OUT_DIR = Path("/mnt/sata/pointbot/out")


class MediaService:
    def __init__(self, root: Path):
        self.paths: MediaPaths = ensure_media_paths(root)
        self.db = MediaDatabase(self.paths.db_path)
        self.youtube = YouTubeService(self.paths, self.db)
        self.torrent_service = TorrentService(ensure_app_paths(root))
        self.codex = CodexRuntime()
        self.codex_sdk = CodexSDK(root)

    def list_codex_threads(self, limit: int = 20, model: str | None = None) -> list[dict[str, str]]:
        try:
            return self.codex_sdk.list_threads(limit=limit, model=model)
        except (CodexAuthError, CodexSetupError, Exception):
            return []

    def list_codex_messages(
        self,
        thread_id: str | None,
        model: str | None = None,
        sandbox: str = "write",
    ) -> list[dict[str, str]]:
        if not thread_id:
            return []
        try:
            return self.codex_sdk.read_thread(thread_id, model=model, sandbox=sandbox)
        except (CodexAuthError, CodexSetupError, Exception):
            return []

    def list_codex_models(self) -> list[dict[str, str]]:
        try:
            return self.codex_sdk.list_models()
        except (CodexAuthError, CodexSetupError, Exception):
            return []

    def list_chat_sessions(self, limit: int = 50, offset: int = 0) -> list[ChatSessionRecord]:
        return self.db.list_chat_sessions(limit=limit, offset=offset)

    def create_chat_session(self) -> ChatSessionRecord:
        return self.db.create_chat_session()

    def list_chat_messages(self, session_id: str = "default") -> list[dict[str, str | None]]:
        self._ensure_pending_metadata_prompts(session_id=session_id)
        return [
            {
                "role": item.role,
                "content": item.content,
                "model": item.model,
                "artifact": self._extract_chat_artifact(item.content),
            }
            for item in self.db.list_chat_messages(session_id=session_id)
        ]

    def add_chat_message(
        self,
        role: str,
        content: str,
        model: str | None = None,
        session_id: str = "default",
    ) -> None:
        self.db.add_chat_message(role=role, content=content, model=model, session_id=session_id)

    def enqueue_youtube(
        self,
        url: str,
        metadata: dict[str, str] | None = None,
        treat_as_playlist: bool = False,
    ) -> DownloadRecord:
        return self.youtube.enqueue(url, metadata=metadata, treat_as_playlist=treat_as_playlist)

    def retry_youtube_download(self, download_id: str) -> DownloadRecord | None:
        record = self.db.get_download(download_id)
        if record is None:
            return None
        details = self._load_download_details(record)
        metadata = details.get("metadata", {})
        if record.source_kind in {"youtube", "youtube_playlist"}:
            return self.youtube.enqueue(
                record.source_value,
                metadata=metadata,
                treat_as_playlist=record.source_kind == "youtube_playlist",
            )
        return None

    def add_torrent_from_magnet(self, magnet: str) -> TorrentRecord:
        name = self._extract_magnet_name(magnet) or magnet
        media_type = classify_media(name)
        target_dir = self.paths.music_dir if media_type == "music" else self.paths.movies_dir
        record = self.torrent_service.add_magnets([magnet], download_dir=str(target_dir))[0]
        self._sync_torrent_to_download(record, media_type)
        return record

    def add_torrent_file(
        self,
        filename: str,
        payload: bytes,
    ) -> TorrentRecord:
        media_type = classify_media(filename)
        target_dir = self.paths.music_dir if media_type == "music" else self.paths.movies_dir
        record = self.torrent_service.add_torrent_file(
            filename=filename,
            payload=payload,
            download_dir=str(target_dir),
        )
        inferred_media_type = classify_media(record.name or filename)
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

    def clear_chat(self, session_id: str = "default") -> None:
        self.db.clear_chat_messages(session_id=session_id)

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

    def handle_chat_submission(
        self,
        prompt: str,
        uploaded_torrents: list[tuple[str, bytes]],
        session_id: str = "default",
        current_thread_id: str | None = None,
        model: str | None = None,
        effort: str = "medium",
        sandbox: str = "write",
    ) -> dict[str, str | None]:
        prompt = prompt.strip()
        if not prompt:
            prompt = "Processe os arquivos .torrent anexados."
        action_notes: list[str] = []

        slash_reply = self._handle_slash_command(
            prompt,
            current_thread_id=current_thread_id,
            model=model,
            effort=effort,
            session_id=session_id,
        )
        if slash_reply:
            self.add_chat_message("assistant", str(slash_reply["reply"]), model="codex-cli", session_id=session_id)
            return slash_reply

        youtube_urls = self._extract_youtube_urls(prompt)
        magnets = self._extract_magnets(prompt)
        pending = self._latest_pending_youtube_info()
        metadata = self._extract_music_metadata(prompt, pending)

        if not youtube_urls and not magnets and not uploaded_torrents:
            if self._looks_like_pointbot_pdf_request(prompt):
                reply = self._pointbot_pdf_download_reply()
                self.add_chat_message("assistant", reply, model="pointbot-orcamentos", session_id=session_id)
                self.add_chat_message("user", prompt, model=None, session_id=session_id)
                return {"reply": reply, "thread_id": current_thread_id}

            if self._looks_like_status_question(prompt):
                reply = self.summarize_download_status()
                self.add_chat_message("assistant", reply, model="download_status", session_id=session_id)
                self.add_chat_message("user", prompt, model=None, session_id=session_id)
                return {"reply": reply, "thread_id": current_thread_id}

            if pending:
                pending_details = self._load_download_details(pending)
                pending_metadata = pending_details.get("metadata", {})
                merged_metadata = {**pending_metadata, **metadata}
                if merged_metadata.get("artist") and merged_metadata.get("album"):
                    resumed = self.youtube.resume_with_metadata(pending.id, merged_metadata)
                    reply = (
                        "Perfeito, atualizei os metadados e coloquei a musica de volta na fila. "
                        f"Ela sera organizada em `{self.paths.music_dir / merged_metadata['artist'] / merged_metadata['album']}`. "
                        "Acompanhe o progresso na aba Downloads."
                    )
                    if resumed is None:
                        reply = "Nao consegui encontrar a musica pendente para retomar."
                    self.add_chat_message("user", prompt, model=None, session_id=session_id)
                    self.add_chat_message("assistant", reply, model="youtube_music", session_id=session_id)
                    return {"reply": reply, "thread_id": current_thread_id}
                missing = []
                if not merged_metadata.get("artist"):
                    missing.append("artista")
                if not merged_metadata.get("album"):
                    missing.append("album")
                reply = (
                    f"Ainda preciso de {' e '.join(missing)} para organizar a musica. "
                    "Me envie aqui no chat no formato: `artista: Nome, album: Nome, musica: Nome`."
                )
                self.add_chat_message("user", prompt, model=None, session_id=session_id)
                self.add_chat_message("assistant", reply, model="youtube_music", session_id=session_id)
                return {"reply": reply, "thread_id": current_thread_id}

        for url in youtube_urls:
            job = self.enqueue_youtube(
                url,
                metadata=metadata,
                treat_as_playlist=self._should_treat_as_playlist(url, prompt),
            )
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
            torrent = self.add_torrent_from_magnet(magnet)
            action_notes.append(f"Torrent magnet: {torrent.name} -> {torrent.download_dir} [{torrent.status}]")

        for filename, payload in uploaded_torrents:
            torrent = self.add_torrent_file(filename, payload)
            action_notes.append(f"Arquivo .torrent: {torrent.name} -> {torrent.download_dir} [{torrent.status}]")

        if action_notes:
            self.add_chat_message("user", prompt, model=None, session_id=session_id)
            reply = (
                "\n".join(action_notes)
                + "\n\nColoquei na fila de downloads. Acompanhe o progresso na aba Downloads."
            )
            self.add_chat_message("assistant", reply, model="skills", session_id=session_id)
            return {"reply": reply, "thread_id": current_thread_id}

        if self.codex_sdk.is_available():
            try:
                result = self.codex_sdk.ask(
                    prompt=prompt,
                    thread_id=current_thread_id,
                    model=model,
                    effort=effort,
                    sandbox=sandbox,
                )
                return {"reply": result.reply, "thread_id": result.thread_id}
            except (CodexAuthError, CodexSetupError) as exc:
                return {"reply": str(exc), "thread_id": current_thread_id}
            except Exception as exc:
                return {
                    "reply": f"O Codex SDK falhou ao processar esta mensagem: {exc}",
                    "thread_id": current_thread_id,
                }

        reply = (
            "O Codex SDK ainda nao esta disponivel neste ambiente. "
            "Instale `openai-codex` para usar o chat normal do Codex aqui."
        )
        return {"reply": reply, "thread_id": current_thread_id}

    def _handle_slash_command(
        self,
        prompt: str,
        current_thread_id: str | None = None,
        model: str | None = None,
        effort: str = "medium",
        session_id: str = "default",
    ) -> dict[str, str | None] | None:
        parts = prompt.strip().split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        if not command.startswith("/"):
            return None
        if command == "/help":
            return {
                "reply": self.codex.command_help(),
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command == "/status":
            return {
                "reply": self.codex.render_status() + "\n\n" + self.summarize_download_status(),
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command == "/models":
            models = self.list_codex_models()
            if not models:
                reply = "Nenhum modelo retornado pelo Codex SDK neste ambiente."
            else:
                lines = ["Modelos do Codex:"]
                for item in models:
                    suffix = " (default)" if item.get("default") else ""
                    lines.append(f"- `{item['id']}`{suffix}")
                reply = "\n".join(lines)
            return {
                "reply": reply,
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command == "/model":
            if not argument:
                reply = f"Modelo atual: `{model or 'default do Codex'}`"
                return {
                    "reply": reply,
                    "thread_id": current_thread_id,
                    "model": model,
                    "effort": effort,
                }
            return {
                "reply": f"Modelo alterado para `{argument}`.",
                "thread_id": current_thread_id,
                "model": argument,
                "effort": effort,
            }
        if command == "/effort":
            if not argument:
                return {
                    "reply": f"Effort atual: `{effort}`",
                    "thread_id": current_thread_id,
                    "model": model,
                    "effort": effort,
                }
            if argument not in {"low", "medium", "high"}:
                return {
                    "reply": "Uso: `/effort low|medium|high`",
                    "thread_id": current_thread_id,
                    "model": model,
                    "effort": effort,
                }
            return {
                "reply": f"Effort alterado para `{argument}`.",
                "thread_id": current_thread_id,
                "model": model,
                "effort": argument,
            }
        if command == "/threads":
            threads = self.list_codex_threads(limit=20, model=model)
            if not threads:
                reply = "Nenhuma thread do Codex encontrada."
            else:
                lines = ["Ultimas threads do Codex:"]
                for item in threads:
                    lines.append(f"- `{item['id']}` {item['name']}")
                reply = "\n".join(lines)
            return {
                "reply": reply,
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command == "/sandbox":
            if not argument:
                return {
                    "reply": "Sandbox atual: use o seletor lateral ou `/sandbox read|write|full`.",
                    "thread_id": current_thread_id,
                    "model": model,
                    "effort": effort,
                }
            if argument not in {"read", "write", "full"}:
                return {
                    "reply": "Uso: `/sandbox read|write|full`",
                    "thread_id": current_thread_id,
                    "model": model,
                    "effort": effort,
                }
            return {
                "reply": f"Sandbox alterado para `{argument}`.",
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
                "sandbox": argument,
            }
        if command == "/resume":
            if not argument:
                return {
                    "reply": "Uso: `/resume THREAD_ID`",
                    "thread_id": current_thread_id,
                    "model": model,
                    "effort": effort,
                }
            return {
                "reply": f"Thread retomada: `{argument}`.",
                "thread_id": argument,
                "model": model,
                "effort": effort,
            }
        if command in {"/skills", "/skill"}:
            return {
                "reply": render_skills(),
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command == "/pointbot":
            if self._looks_like_pointbot_pdf_request(prompt):
                reply = self._pointbot_pdf_download_reply()
            else:
                reply = (
                    "Skill `pointbot-orcamentos` disponivel para uso pelo Codex neste projeto.\n"
                    "- Use quando quiser cotacao/orcamento da Point Viagens.\n"
                    "- O fluxo usa o projeto `/mnt/sata/pointbot`, gera HTML/PDF quando necessario e so envia email apos confirmacao.\n"
                    "- Use `/pointbot pdf` para baixar no chat o PDF mais recente gerado em `/mnt/sata/pointbot/out`.\n"
                    "- Para iniciar, descreva destino, datas, viajantes e produtos desejados."
                )
            return {
                "reply": reply,
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command in {"/downloads", "/download"}:
            return {
                "reply": self.summarize_download_status(limit=10),
                "thread_id": current_thread_id,
                "model": model,
                "effort": effort,
            }
        if command == "/new":
            return {
                "reply": "Novo chat iniciado.",
                "thread_id": None,
                "model": model,
                "effort": effort,
            }
        return {
            "reply": "Comando desconhecido. Use `/help` para ver os comandos disponiveis.",
            "thread_id": current_thread_id,
            "model": model,
            "effort": effort,
        }

    def preview_activity(
        self,
        prompt: str,
        uploaded_torrents: list[tuple[str, bytes]],
        model: str | None = None,
        effort: str = "medium",
        sandbox: str = "write",
        current_thread_id: str | None = None,
    ) -> list[str]:
        steps = [f"Modelo: `{model or 'default do Codex'}` | effort: `{effort}` | sandbox: `{sandbox}`"]
        if uploaded_torrents:
            steps.append(f"Lendo {len(uploaded_torrents)} arquivo(s) .torrent anexado(s).")
        youtube_urls = self._extract_youtube_urls(prompt or "")
        magnets = self._extract_magnets(prompt or "")
        if youtube_urls:
            steps.append(f"Roteando para skill de YouTube com {len(youtube_urls)} link(s).")
            steps.append("Preparando fila e destino dos arquivos de audio.")
        if magnets:
            steps.append(f"Roteando para skill de torrent com {len(magnets)} magnet(s).")
            steps.append("Registrando download e monitoramento local do torrent.")
        if self._looks_like_pointbot_pdf_request(prompt or ""):
            steps.append("Procurando PDF mais recente do Pointbot no disco.")
        elif prompt.strip().startswith("/"):
            steps.append("Executando comando slash do app.")
        elif not youtube_urls and not magnets and not uploaded_torrents:
            if current_thread_id:
                steps.append(f"Retomando thread `{current_thread_id}` do Codex.")
            else:
                steps.append("Abrindo nova thread do Codex.")
            steps.append("Enviando prompt para o Codex SDK.")
            steps.append("Aguardando resposta final do modelo.")
        return steps

    def _pointbot_pdf_download_reply(self) -> str:
        pdf_path = self._latest_pointbot_pdf()
        if pdf_path is None:
            return (
                "Ainda nao encontrei PDF de cotacao em `/mnt/sata/pointbot/out`. "
                "Gere o PDF pela skill `pointbot-orcamentos` e depois use `/pointbot pdf`."
            )
        artifact = {
            "kind": "download",
            "path": str(pdf_path),
            "filename": pdf_path.name,
            "mime": "application/pdf",
            "label": "Baixar PDF da cotacao",
        }
        return (
            f"PDF mais recente da Point Viagens disponivel para download: `{pdf_path.name}`.\n\n"
            f"<!-- chat-media-artifact {json.dumps(artifact, ensure_ascii=True)} -->"
        )

    @staticmethod
    def _latest_pointbot_pdf() -> Path | None:
        if not POINTBOT_OUT_DIR.exists():
            return None
        pdfs = [path for path in POINTBOT_OUT_DIR.glob("*.pdf") if path.is_file()]
        if not pdfs:
            return None
        return max(pdfs, key=lambda path: path.stat().st_mtime)

    @staticmethod
    def _looks_like_pointbot_pdf_request(prompt: str) -> bool:
        normalized = prompt.lower()
        wants_file = any(term in normalized for term in ("pdf", "download", "baixar", "baixa", "anexo"))
        mentions_quote = any(term in normalized for term in ("pointbot", "point bot", "cotacao", "cotação", "orcamento", "orçamento"))
        return wants_file and mentions_quote

    @staticmethod
    def _extract_chat_artifact(content: str) -> dict[str, str] | None:
        match = re.search(r"<!-- chat-media-artifact (\{.*?\}) -->", content or "", flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(1))
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("kind") != "download":
            return None
        path = Path(str(payload.get("path", "")))
        if not path.is_file():
            return None
        return {
            "path": str(path),
            "filename": str(payload.get("filename") or path.name),
            "mime": str(payload.get("mime") or "application/octet-stream"),
            "label": str(payload.get("label") or "Baixar arquivo"),
        }

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

    def _ensure_pending_metadata_prompts(self, session_id: str = "default") -> None:
        for item in self.db.list_downloads(limit=50):
            if item.source_kind != "youtube" or item.status != "needs_info":
                continue
            details = self._load_download_details(item)
            if details.get("metadata_request_sent"):
                continue
            metadata = details.get("metadata", {})
            missing = [field for field in ("artist", "album") if not metadata.get(field)]
            if not missing:
                continue
            details["metadata_request_sent"] = True
            self.db.upsert_download(item.copy(details_json=json.dumps(details), updated_at=utc_now()))
            self.db.add_chat_message(
                "assistant",
                self.youtube._build_metadata_request_message(item, metadata, missing),
                model=None,
                session_id=session_id,
            )

    @staticmethod
    def _extract_youtube_urls(text: str) -> list[str]:
        pattern = r"(https?://(?:www\.)?(?:youtube\.com/(?:watch|playlist)\?[^\s]+|youtu\.be/[^\s]+))"
        return [url.rstrip(".,);]") for url in re.findall(pattern, text or "")]

    def _should_treat_as_playlist(self, url: str, prompt: str) -> bool:
        if self.youtube.is_explicit_playlist_url(url):
            return True
        normalized = prompt.lower()
        playlist_terms = (
            "playlist inteira",
            "playlist toda",
            "album inteiro",
            "álbum inteiro",
            "lista inteira",
            "baixa a playlist",
            "baixar a playlist",
        )
        return any(term in normalized for term in playlist_terms)

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

    def _extract_music_metadata(self, prompt: str, pending: DownloadRecord | None = None) -> dict[str, str]:
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

        if pending and "album" not in metadata:
            details = self._load_download_details(pending)
            pending_metadata = details.get("metadata", {})
            only_missing_album = bool(pending_metadata.get("artist")) and not pending_metadata.get("album")
            if only_missing_album:
                album = self._extract_album_from_natural_reply(prompt)
                if album:
                    metadata["album"] = album
        return metadata

    @staticmethod
    def _extract_album_from_natural_reply(prompt: str) -> str | None:
        text = prompt.strip().strip(".")
        if not text:
            return None
        normalized = text.lower()
        ignored_replies = (
            "o resto vc ja tem",
            "o resto voce ja tem",
            "o resto você já tem",
            "vc ja tem",
            "voce ja tem",
            "você já tem",
        )
        if normalized in ignored_replies or "resto" in normalized:
            return None

        patterns = (
            r"^(?:coloca|coloque|salva|salve|usa|use)\s+(?:como|em|no album|no álbum)?\s*(.+)$",
            r"^(?:o\s+)?(?:album|álbum)\s+(?:e|é|eh|seria|vai ser)\s+(.+)$",
            r"^(?:pode ser|chama de|nomeia como)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return MediaService._clean_metadata_value(match.group(1))

        if len(text.split()) <= 6 and not any(marker in text for marker in ("http://", "https://", "magnet:")):
            return MediaService._clean_metadata_value(text)
        return None

    @staticmethod
    def _clean_metadata_value(value: str) -> str:
        cleaned = value.strip().strip("`'\"")
        cleaned = re.sub(r"^(?:como|album|álbum)\s+", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" .,:;")


@st.cache_resource(show_spinner=False)
def get_media_service() -> MediaService:
    return MediaService(Path.cwd())
