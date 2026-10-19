"""Deterministic services for web tests; never invoke Codex or download files."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

from media_manager.codex_sdk import CodexAskResult
from torrent_manager.models import EngineSnapshot, TorrentRecord


class FakeSDK:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.interrupted = threading.Event()
        self.block = False
        self.delay = 0
        self.history = {}

    def is_available(self):
        return True

    def ask(self, prompt, thread_id=None, on_event=None, on_turn=None, **kwargs):
        self.interrupted.clear()
        active_id = thread_id or "thread-live"
        self.history.setdefault(active_id, []).append({"role": "user", "content": prompt})
        on_event({"type": "thread", "thread_id": active_id})
        on_turn(SimpleNamespace(interrupt=self.interrupted.set))
        self.started.set()
        on_event({"type": "message", "id": "commentary", "phase": "commentary", "text": "Vou conferir os arquivos e organizar a fila."})
        on_event({"type": "activity", "id": "cmd", "label": "Executando comando", "detail": "ls -lah media/", "done": False, "status": "running"})
        if self.block:
            while not self.release.wait(.01):
                if self.interrupted.is_set():
                    raise InterruptedError()
        if self.delay:
            for _ in range(int(self.delay * 50)):
                if self.interrupted.wait(.02):
                    raise InterruptedError()
        if prompt == "falhar":
            raise RuntimeError("Falha de teste")
        on_event({"type": "activity", "id": "cmd", "label": "Executando comando", "detail": "ls -lah media/", "done": True, "status": "completed"})
        on_event({"type": "plan", "explanation": "Conferência da biblioteca", "steps": [{"step": "Listar arquivos", "status": "completed"}]})
        for chunk in ["## Tudo pronto\n\n", "Encontrei **3 downloads** ", "na sua fila.\n\n```sh\nls media/\n```"]:
            on_event({"type": "message", "id": "answer", "phase": "final_answer", "delta": chunk})
        text = "## Tudo pronto\n\nEncontrei **3 downloads** na sua fila.\n\n```sh\nls media/\n```"
        on_event({"type": "message", "id": "answer", "phase": "final_answer", "text": text})
        self.history[active_id].append({"role": "assistant", "content": text})
        return CodexAskResult(thread_id or "thread-live", text)


def fake_service():
    service = Mock()
    service.codex_sdk = FakeSDK()
    service.codex_error.return_value = None
    service.list_codex_models.return_value = [{"id": "test-model", "name": "Modelo de teste"}]
    service.list_codex_skills.return_value = [{"name": "organizar-midia", "path": "/skills/SKILL.md"}]
    service.list_codex_threads.return_value = [{"id": "thread-old", "name": "Organizar minha biblioteca", "preview": "Músicas", "updated_at": "1792368000"}]
    service.list_codex_messages.return_value = [{"role": "user", "content": "Olá"}, {"role": "assistant", "content": "Como posso ajudar?"}]
    service.list_codex_messages.side_effect = lambda thread_id, **kwargs: service.codex_sdk.history.get(
        thread_id, service.list_codex_messages.return_value)
    engine = service.torrent_service
    engine.get_default_download_dir.return_value = "/app/downloads"
    engine.get_engine_snapshot.return_value = EngineSnapshot(True, "Motor ativo", download_rate=1024, peers=3)
    engine.list_torrents.return_value = [TorrentRecord(id="torrent-test", name="Meu download", source_type="magnet", source_value="magnet:?xt=urn:btih:test", download_dir="/app/downloads", progress=.4, status="downloading")]
    engine.list_events.return_value = []
    engine.list_files.return_value = []
    return service
