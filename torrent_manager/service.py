from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any
import socket
from urllib.parse import parse_qs, unquote, urlparse

from .config import AppPaths
from .db import Database
from .models import (
    ACTIVE_STATUSES,
    EngineSnapshot,
    EventRecord,
    SourceType,
    TorrentFileRecord,
    TorrentRecord,
    TorrentStatus,
)
from .utils import utc_now

try:
    import libtorrent as lt
except ImportError:  # pragma: no cover
    lt = None


class TorrentService:
    POLL_INTERVAL_SECONDS = 1.0
    RESUME_DUMP_INTERVAL_SECONDS = 20.0

    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.db = Database(paths.db_path)
        self.db.set_default_setting("default_download_dir", str(paths.downloads_dir))
        self.lock = threading.RLock()
        self.records: dict[str, TorrentRecord] = {
            record.id: record for record in self.db.list_torrents(include_removed=True)
        }
        self.handles: dict[str, Any] = {}
        self._event_timestamps: dict[tuple[str | None, str, str], float] = {}
        self._last_resume_dump = 0.0
        self._running = False
        self.thread: threading.Thread | None = None
        self.engine_available = False
        self.engine_message = "Backend BitTorrent indisponivel."
        self.session = None

        if lt is None:
            self._log_event(
                None,
                "warning",
                "libtorrent nao esta instalado. O app mostra o historico, mas nao inicia downloads.",
                dedupe_window=3600,
            )
            return

        try:
            self.session = self._build_session()
            self.engine_available = True
            self.engine_message = "Motor BitTorrent ativo."
            self._restore_active_torrents()
            self._running = True
            self.thread = threading.Thread(
                target=self._worker_loop,
                name="torrent-service-loop",
                daemon=True,
            )
            self.thread.start()
            self._log_event(None, "success", "Motor BitTorrent inicializado.", dedupe_window=3600)
        except Exception as exc:
            self.engine_available = False
            self.engine_message = f"Falha ao iniciar o motor: {exc}"
            self._log_event(None, "error", self.engine_message, dedupe_window=3600)

    def add_magnets(self, magnets: list[str], download_dir: str, start_paused: bool = False) -> list[TorrentRecord]:
        created: list[TorrentRecord] = []
        resolved_dir = self._resolve_download_dir(download_dir)
        self.set_default_download_dir(str(resolved_dir))
        for magnet in magnets:
            magnet = magnet.strip()
            if not magnet:
                continue
            record = TorrentRecord(
                id=uuid.uuid4().hex,
                name=self._extract_magnet_name(magnet) or "Magnet sem nome",
                source_type=SourceType.MAGNET,
                source_value=magnet,
                download_dir=str(resolved_dir),
                status=TorrentStatus.PAUSED if start_paused else TorrentStatus.QUEUED,
            )
            with self.lock:
                self._save_record(record)
                self._log_event(record.id, "info", "Torrent adicionado via magnet.")
                try:
                    handle = self._ensure_handle(record, start_paused=start_paused)
                    if start_paused:
                        handle.pause()
                    refreshed = self._refresh_record(record.id)
                    created.append(refreshed)
                except Exception as exc:
                    failed = record.copy(
                        status=TorrentStatus.ERROR,
                        error_message=str(exc),
                        updated_at=utc_now(),
                    )
                    self._save_record(failed)
                    self._log_event(record.id, "error", f"Falha ao adicionar magnet: {exc}")
                    created.append(failed)
        return created

    def add_torrent_file(self, filename: str, payload: bytes, download_dir: str, start_paused: bool = False) -> TorrentRecord:
        resolved_dir = self._resolve_download_dir(download_dir)
        self.set_default_download_dir(str(resolved_dir))
        torrent_id = uuid.uuid4().hex
        stored_path = self.paths.torrents_dir / f"{torrent_id}-{Path(filename).name}"
        stored_path.write_bytes(payload)

        try:
            if lt is None:
                raise RuntimeError("libtorrent nao esta disponivel.")
            torrent_info = lt.torrent_info(str(stored_path))
            record = TorrentRecord(
                id=torrent_id,
                name=torrent_info.name(),
                source_type=SourceType.TORRENT_FILE,
                source_value=str(stored_path),
                torrent_file_path=str(stored_path),
                info_hash=self._stringify_hash(torrent_info.info_hash()),
                download_dir=str(resolved_dir),
                status=TorrentStatus.PAUSED if start_paused else TorrentStatus.QUEUED,
                total_size=int(torrent_info.total_size()),
                metadata_ready=True,
                file_count=int(torrent_info.files().num_files()),
            )
        except Exception as exc:
            record = TorrentRecord(
                id=torrent_id,
                name=Path(filename).stem or "Torrent invalido",
                source_type=SourceType.TORRENT_FILE,
                source_value=str(stored_path),
                torrent_file_path=str(stored_path),
                download_dir=str(resolved_dir),
                status=TorrentStatus.ERROR,
                error_message=f"Nao foi possivel ler o arquivo .torrent: {exc}",
            )
            with self.lock:
                self._save_record(record)
                self._log_event(record.id, "error", record.error_message or "Arquivo .torrent invalido.")
            return record

        with self.lock:
            self._save_record(record)
            self._log_event(record.id, "info", "Torrent adicionado via arquivo .torrent.")
            try:
                handle = self._ensure_handle(record, start_paused=start_paused)
                if start_paused:
                    handle.pause()
                return self._refresh_record(record.id)
            except Exception as exc:
                failed = record.copy(
                    status=TorrentStatus.ERROR,
                    error_message=str(exc),
                    updated_at=utc_now(),
                )
                self._save_record(failed)
                self._log_event(record.id, "error", f"Falha ao iniciar torrent: {exc}")
                return failed

    def pause_torrent(self, torrent_id: str) -> TorrentRecord | None:
        with self.lock:
            record = self.records.get(torrent_id)
            if not record:
                return None
            handle = self.handles.get(torrent_id)
            if handle and handle.is_valid():
                handle.pause()
                self._request_resume_dump_for_handle(handle)
            updated = record.copy(
                status=TorrentStatus.COMPLETED if record.progress >= 1 else TorrentStatus.PAUSED,
                download_rate=0,
                upload_rate=0,
                eta_seconds=None,
                updated_at=utc_now(),
            )
            self._save_record(updated)
            self._log_event(torrent_id, "info", "Torrent pausado.")
            return updated

    def resume_torrent(self, torrent_id: str) -> TorrentRecord | None:
        with self.lock:
            record = self.records.get(torrent_id)
            if not record:
                return None
            if not self.engine_available:
                failed = record.copy(
                    status=TorrentStatus.ERROR,
                    error_message=self.engine_message,
                    updated_at=utc_now(),
                )
                self._save_record(failed)
                return failed
            try:
                handle = self._ensure_handle(record, start_paused=False)
                handle.resume()
                self._log_event(torrent_id, "info", "Torrent retomado.")
                return self._refresh_record(torrent_id)
            except Exception as exc:
                failed = record.copy(
                    status=TorrentStatus.ERROR,
                    error_message=str(exc),
                    updated_at=utc_now(),
                )
                self._save_record(failed)
                self._log_event(torrent_id, "error", f"Falha ao retomar torrent: {exc}")
                return failed

    def force_recheck(self, torrent_id: str) -> TorrentRecord | None:
        with self.lock:
            record = self.records.get(torrent_id)
            if not record:
                return None
            try:
                handle = self._ensure_handle(record, start_paused=False)
                handle.force_recheck()
                self._log_event(torrent_id, "info", "Revalidacao forcada iniciada.")
                return self._refresh_record(torrent_id)
            except Exception as exc:
                failed = record.copy(
                    status=TorrentStatus.ERROR,
                    error_message=str(exc),
                    updated_at=utc_now(),
                )
                self._save_record(failed)
                self._log_event(torrent_id, "error", f"Falha ao revalidar torrent: {exc}")
                return failed

    def remove_torrent(self, torrent_id: str, delete_files: bool = False) -> TorrentRecord | None:
        with self.lock:
            record = self.records.get(torrent_id)
            if not record:
                return None
            handle = self.handles.pop(torrent_id, None)
            if handle and handle.is_valid() and self.session is not None:
                options = int(lt.options_t.delete_files) if delete_files else 0
                self.session.remove_torrent(handle, options)
            updated = record.copy(
                status=TorrentStatus.REMOVED,
                download_rate=0,
                upload_rate=0,
                eta_seconds=None,
                updated_at=utc_now(),
            )
            self._save_record(updated)
            action = "Torrent removido e dados excluidos." if delete_files else "Torrent removido do cliente."
            self._log_event(torrent_id, "warning", action)
            return updated

    def list_torrents(self, include_removed: bool = False) -> list[TorrentRecord]:
        with self.lock:
            records = list(self.records.values())
        if not include_removed:
            records = [record for record in records if record.status != TorrentStatus.REMOVED]
        return sorted(
            records,
            key=lambda item: (item.status in ACTIVE_STATUSES, item.updated_at, item.added_at),
            reverse=True,
        )

    def get_torrent(self, torrent_id: str) -> TorrentRecord | None:
        with self.lock:
            return self.records.get(torrent_id)

    def list_events(self, limit: int = 200, torrent_id: str | None = None) -> list[EventRecord]:
        return self.db.list_events(limit=limit, torrent_id=torrent_id)

    def list_files(self, torrent_id: str) -> list[TorrentFileRecord]:
        with self.lock:
            record = self.records.get(torrent_id)
            handle = self.handles.get(torrent_id)
            if not record:
                return []

            torrent_info = None
            file_progress: list[int] = []

            if handle and handle.is_valid():
                try:
                    torrent_info = handle.torrent_file()
                    file_progress = list(handle.file_progress())
                except Exception:
                    torrent_info = None

            if torrent_info is None and record.torrent_file_path and Path(record.torrent_file_path).exists() and lt is not None:
                try:
                    torrent_info = lt.torrent_info(str(record.torrent_file_path))
                except Exception:
                    torrent_info = None

            if torrent_info is None:
                return []

            files = torrent_info.files()
            rows: list[TorrentFileRecord] = []
            for index in range(files.num_files()):
                size = int(files.file_size(index))
                downloaded = int(file_progress[index]) if index < len(file_progress) else 0
                if record.progress >= 1 and downloaded == 0:
                    downloaded = size
                progress = (downloaded / size) if size else 0.0
                rows.append(
                    TorrentFileRecord(
                        path=str(files.file_path(index)),
                        size=size,
                        downloaded=downloaded,
                        progress=progress,
                    )
                )
            return rows

    def get_engine_snapshot(self) -> EngineSnapshot:
        if not self.engine_available or self.session is None:
            return EngineSnapshot(available=False, message=self.engine_message)
        try:
            status = self.session.status()
            return EngineSnapshot(
                available=True,
                message=self.engine_message,
                download_rate=int(status.download_rate),
                upload_rate=int(status.upload_rate),
                peers=int(status.num_peers),
                dht_nodes=int(status.dht_nodes),
                has_incoming_connections=bool(status.has_incoming_connections),
            )
        except Exception as exc:
            return EngineSnapshot(available=True, message=f"Motor ativo com alerta: {exc}")

    def get_default_download_dir(self) -> str:
        return self.db.get_setting("default_download_dir", str(self.paths.downloads_dir)) or str(self.paths.downloads_dir)

    def set_default_download_dir(self, value: str) -> str:
        resolved = self._resolve_download_dir(value)
        self.db.set_setting("default_download_dir", str(resolved))
        return str(resolved)

    def _build_session(self) -> Any:
        session = lt.session()
        alert_mask = (
            int(lt.alert.category_t.status_notification)
            | int(lt.alert.category_t.error_notification)
            | int(lt.alert.category_t.storage_notification)
            | int(lt.alert.category_t.tracker_notification)
        )
        outbound_ip = self._detect_outbound_ip()
        listen_interfaces = "0.0.0.0:6881,[::]:6881"
        if outbound_ip:
            listen_interfaces = f"{outbound_ip}:6881,[::]:6881"

        settings = {
            "user_agent": "streamlito/1.0",
            "listen_interfaces": listen_interfaces,
            "enable_dht": True,
            "enable_lsd": True,
            "enable_upnp": True,
            "enable_natpmp": True,
            "alert_mask": alert_mask,
        }
        if outbound_ip:
            settings["announce_ip"] = outbound_ip
            settings["outgoing_interfaces"] = outbound_ip
        session.apply_settings(settings)
        session.start_dht()
        session.start_lsd()
        session.start_upnp()
        session.start_natpmp()
        return session

    @staticmethod
    def _detect_outbound_ip() -> str | None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
            return None if address.startswith("127.") else address
        except OSError:
            return None
        finally:
            probe.close()

    def _restore_active_torrents(self) -> None:
        for record in self.list_torrents(include_removed=True):
            if record.status not in ACTIVE_STATUSES:
                continue
            try:
                self._ensure_handle(record, start_paused=False)
            except Exception as exc:
                failed = record.copy(
                    status=TorrentStatus.ERROR,
                    error_message=f"Falha ao restaurar torrent: {exc}",
                    updated_at=utc_now(),
                )
                self._save_record(failed)
                self._log_event(record.id, "error", failed.error_message or "Falha ao restaurar torrent.")

    def _worker_loop(self) -> None:
        while self._running:
            with self.lock:
                self._consume_alerts()
                for torrent_id in list(self.handles):
                    self._refresh_record(torrent_id)
                if time.time() - self._last_resume_dump >= self.RESUME_DUMP_INTERVAL_SECONDS:
                    self._request_resume_dump()
                    self._last_resume_dump = time.time()
                self._prune_event_cache()
            time.sleep(self.POLL_INTERVAL_SECONDS)

    def _consume_alerts(self) -> None:
        if self.session is None:
            return
        for alert in self.session.pop_alerts():
            torrent_id = self._find_torrent_id_for_handle(getattr(alert, "handle", None))
            alert_type = type(alert).__name__

            if lt is not None and isinstance(alert, lt.save_resume_data_alert):
                self._store_resume_data(torrent_id, alert)
                continue
            if lt is not None and isinstance(alert, lt.save_resume_data_failed_alert):
                self._log_event(torrent_id, "warning", f"Falha ao salvar estado: {alert.message()}", dedupe_window=120)
                continue
            if lt is not None and isinstance(alert, lt.metadata_received_alert):
                self._log_event(torrent_id, "success", "Metadados do torrent recebidos.", dedupe_window=600)
                if torrent_id:
                    self._refresh_record(torrent_id)
                continue
            if lt is not None and isinstance(alert, lt.torrent_finished_alert):
                self._log_event(torrent_id, "success", "Download concluido; agora em modo seed.", dedupe_window=600)
                if torrent_id:
                    self._refresh_record(torrent_id)
                continue
            if lt is not None and isinstance(alert, lt.torrent_error_alert):
                self._mark_error(torrent_id, alert.message())
                continue
            if lt is not None and isinstance(alert, lt.file_error_alert):
                self._mark_error(torrent_id, f"Erro de arquivo: {alert.message()}")
                continue
            if lt is not None and isinstance(alert, lt.tracker_error_alert):
                self._log_event(torrent_id, "warning", f"Tracker com erro: {alert.message()}", dedupe_window=120)
                continue
            if alert_type in {"state_changed_alert", "torrent_paused_alert", "torrent_resumed_alert"} and torrent_id:
                self._refresh_record(torrent_id)

    def _mark_error(self, torrent_id: str | None, message: str) -> None:
        if not torrent_id:
            self._log_event(None, "error", message, dedupe_window=120)
            return
        record = self.records.get(torrent_id)
        if not record:
            return
        updated = record.copy(
            status=TorrentStatus.ERROR,
            error_message=message,
            download_rate=0,
            upload_rate=0,
            eta_seconds=None,
            updated_at=utc_now(),
        )
        self._save_record(updated)
        self._log_event(torrent_id, "error", message, dedupe_window=120)

    def _refresh_record(self, torrent_id: str) -> TorrentRecord:
        record = self.records[torrent_id]
        handle = self.handles.get(torrent_id)
        if not handle or not handle.is_valid():
            return record

        try:
            status = handle.status()
        except Exception as exc:
            failed = record.copy(status=TorrentStatus.ERROR, error_message=str(exc), updated_at=utc_now())
            self._save_record(failed)
            return failed

        next_status = self._map_status(status, record)
        progress = float(status.progress)
        total_size = int(status.total_wanted or record.total_size)
        downloaded = int(status.total_wanted_done or record.downloaded)
        uploaded = int(max(status.total_upload, status.all_time_upload, record.uploaded))
        download_rate = int(status.download_rate)
        upload_rate = int(status.upload_rate)
        eta_seconds = None
        if next_status in {TorrentStatus.QUEUED, TorrentStatus.FETCHING_METADATA, TorrentStatus.CHECKING, TorrentStatus.DOWNLOADING} and download_rate > 0 and total_size > downloaded:
            eta_seconds = int((total_size - downloaded) / download_rate)

        info_hash = self._stringify_hash(getattr(status, "info_hash", None)) or record.info_hash
        file_count = record.file_count
        if status.has_metadata:
            try:
                file_count = int(handle.torrent_file().files().num_files())
            except Exception:
                file_count = record.file_count

        completed_at = record.completed_at
        if progress >= 1.0 and completed_at is None:
            completed_at = utc_now()

        updated = record.copy(
            name=status.name or record.name,
            info_hash=info_hash,
            status=next_status,
            progress=progress,
            total_size=total_size,
            downloaded=downloaded,
            uploaded=uploaded,
            download_rate=download_rate,
            upload_rate=upload_rate,
            peers=int(status.num_peers),
            seeds=int(status.num_seeds),
            ratio=(uploaded / downloaded) if downloaded > 0 else 0.0,
            eta_seconds=eta_seconds,
            metadata_ready=bool(status.has_metadata),
            file_count=file_count,
            error_message=str(status.error) if status.error else record.error_message if next_status == TorrentStatus.ERROR else None,
            updated_at=utc_now(),
            completed_at=completed_at,
        )
        previous_status = record.status
        self._save_record(updated)
        if previous_status != updated.status:
            self._log_event(torrent_id, "info", f"Status alterado para {updated.status}.", dedupe_window=30)
        return updated

    def _map_status(self, status: Any, record: TorrentRecord) -> str:
        if status.error:
            return TorrentStatus.ERROR
        if status.paused:
            return TorrentStatus.COMPLETED if float(status.progress) >= 1.0 else TorrentStatus.PAUSED

        state = getattr(status.state, "name", str(status.state))
        if state in {"queued_for_checking", "checking_files", "checking_resume_data", "allocating"}:
            return TorrentStatus.CHECKING
        if state == "downloading_metadata":
            return TorrentStatus.FETCHING_METADATA
        if state == "downloading":
            return TorrentStatus.DOWNLOADING
        if state in {"finished", "seeding"} or status.is_seeding:
            return TorrentStatus.SEEDING
        if record.progress > 0:
            return TorrentStatus.DOWNLOADING
        return TorrentStatus.QUEUED

    def _ensure_handle(self, record: TorrentRecord, start_paused: bool = False) -> Any:
        if not self.engine_available or self.session is None or lt is None:
            raise RuntimeError(self.engine_message)

        existing = self.handles.get(record.id)
        if existing and existing.is_valid():
            return existing

        flags = int(lt.add_torrent_params_flags_t.default_flags)
        if start_paused:
            flags |= int(lt.add_torrent_params_flags_t.flag_paused)

        params = None
        if record.resume_data:
            try:
                params = lt.read_resume_data(record.resume_data)
                params.save_path = record.download_dir
                params.flags |= flags
                if record.source_type == SourceType.MAGNET and not params.url:
                    params.url = record.source_value
                if record.source_type == SourceType.TORRENT_FILE and not params.ti and record.torrent_file_path:
                    torrent_path = Path(record.torrent_file_path)
                    if torrent_path.exists():
                        params.ti = lt.torrent_info(str(torrent_path))
            except Exception:
                params = None

        if params is not None:
            handle = self.session.add_torrent(params)
        elif record.source_type == SourceType.MAGNET:
            handle = lt.add_magnet_uri(self.session, record.source_value, {"save_path": record.download_dir, "flags": flags})
        elif record.torrent_file_path and Path(record.torrent_file_path).exists():
            add_params = lt.add_torrent_params()
            add_params.ti = lt.torrent_info(str(record.torrent_file_path))
            add_params.save_path = record.download_dir
            add_params.flags = flags
            handle = self.session.add_torrent(add_params)
        else:
            raise FileNotFoundError("Arquivo .torrent nao encontrado para restauracao.")

        self.handles[record.id] = handle
        return handle

    def _save_record(self, record: TorrentRecord) -> None:
        self.records[record.id] = record
        self.db.upsert_torrent(record)

    def _request_resume_dump(self) -> None:
        for handle in self.handles.values():
            self._request_resume_dump_for_handle(handle)

    @staticmethod
    def _request_resume_dump_for_handle(handle: Any) -> None:
        try:
            if handle.is_valid():
                handle.save_resume_data(int(lt.save_resume_flags_t.only_if_modified))
        except Exception:
            return

    def _store_resume_data(self, torrent_id: str | None, alert: Any) -> None:
        if not torrent_id:
            return
        record = self.records.get(torrent_id)
        if not record:
            return
        payload = None
        try:
            payload = bytes(lt.write_resume_data_buf(alert.params))
        except Exception:
            try:
                if alert.resume_data is not None:
                    payload = bytes(alert.resume_data)
            except Exception:
                payload = None
        if payload is None:
            return
        updated = record.copy(resume_data=payload, updated_at=utc_now())
        self._save_record(updated)

    def _find_torrent_id_for_handle(self, handle: Any) -> str | None:
        if handle is None:
            return None
        for torrent_id, current in self.handles.items():
            try:
                if current == handle:
                    return torrent_id
            except Exception:
                continue
        return None

    def _resolve_download_dir(self, raw_value: str) -> Path:
        candidate = Path(raw_value).expanduser()
        if not candidate.is_absolute():
            candidate = self.paths.root / candidate
        candidate = candidate.resolve()
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def _extract_magnet_name(self, magnet: str) -> str | None:
        parsed = urlparse(magnet)
        values = parse_qs(parsed.query).get("dn")
        if not values:
            return None
        return unquote(values[0]).strip() or None

    def _log_event(self, torrent_id: str | None, level: str, message: str, dedupe_window: int = 0) -> None:
        fingerprint = (torrent_id, level, message)
        now = time.time()
        if dedupe_window > 0:
            previous = self._event_timestamps.get(fingerprint)
            if previous and now - previous < dedupe_window:
                return
            self._event_timestamps[fingerprint] = now
        self.db.add_event(torrent_id, level, message, utc_now())

    def _prune_event_cache(self) -> None:
        cutoff = time.time() - 3600
        stale_keys = [key for key, seen_at in self._event_timestamps.items() if seen_at < cutoff]
        for key in stale_keys:
            self._event_timestamps.pop(key, None)

    @staticmethod
    def _stringify_hash(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text and text != "0000000000000000000000000000000000000000" else None
