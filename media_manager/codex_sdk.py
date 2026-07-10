from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _value(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            value = obj[name]
            if value is not None:
                return value
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _items(obj: Any, *names: str) -> list[Any]:
    if isinstance(obj, list):
        return obj
    value = _value(obj, *names, default=[])
    return list(value or [])


def _history_messages(response: Any) -> list[dict[str, str]]:
    dumped = response.model_dump() if hasattr(response, "model_dump") else response
    thread = _value(dumped, "thread", default=dumped)
    messages: list[dict[str, str]] = []
    for turn in _items(thread, "turns"):
        for item in _items(turn, "items"):
            kind = _value(item, "type")
            if kind == "userMessage":
                chunks = []
                for content in _items(item, "content"):
                    text = _value(content, "text")
                    if text:
                        chunks.append(str(text))
                if chunks:
                    messages.append({"role": "user", "content": "\n".join(chunks)})
            elif kind == "agentMessage":
                phase = str(_value(item, "phase", default=""))
                text = _value(item, "text")
                if phase.endswith("final_answer") and text:
                    messages.append({"role": "assistant", "content": str(text)})
    return messages


@dataclass(frozen=True, slots=True)
class CodexAskResult:
    thread_id: str
    reply: str


class CodexAuthError(RuntimeError):
    pass


class CodexSetupError(RuntimeError):
    pass


def _raise_known_sdk_error(exc: Exception) -> None:
    message = str(exc)
    normalized = message.lower()
    if "401" in normalized or "unauthorized" in normalized or "missing bearer" in normalized:
        raise CodexAuthError(
            "O Codex SDK dentro do Streamlit nao encontrou autenticacao valida. "
            "Defina `OPENAI_API_KEY` no ambiente do `docker compose` ou garanta que o login do Codex esteja disponivel no container."
        ) from exc
    if "readonly database" in normalized or "read-only file system" in normalized or "transportclosederror" in normalized:
        raise CodexSetupError(
            "O Codex SDK encontrou a pasta `~/.codex`, mas nao conseguiu gravar o estado local dentro do container. "
            "Ajustei o mount para leitura e escrita; reinicie o servico para aplicar."
        ) from exc


class CodexSDK:
    def __init__(self, cwd: Path):
        self.cwd = str(cwd.resolve())

    @staticmethod
    def _sandbox(name: str):
        from openai_codex import Sandbox

        mapping = {
            "read": Sandbox.read_only,
            "write": Sandbox.workspace_write,
            "full": Sandbox.full_access,
        }
        return mapping.get(name, Sandbox.workspace_write)

    @staticmethod
    def is_available() -> bool:
        try:
            import openai_codex  # noqa: F401
        except Exception:
            return False
        return True

    def list_models(self) -> list[dict[str, Any]]:
        if not self.is_available():
            return []
        from openai_codex import Codex

        try:
            with Codex() as client:
                response = client.models()
        except Exception as exc:
            _raise_known_sdk_error(exc)
            raise
        rows = _items(response, "data", "models", "items")
        models = []
        for row in rows:
            model_id = str(_value(row, "id", "model", "slug", default=row))
            models.append(
                {
                    "id": model_id,
                    "name": str(_value(row, "display_name", default=model_id)),
                    "default": bool(_value(row, "is_default", default=False)),
                }
            )
        return models

    def list_threads(
        self,
        limit: int = 20,
        model: str | None = None,
        sandbox: str = "write",
    ) -> list[dict[str, str]]:
        if not self.is_available():
            return []
        from openai_codex import Codex

        try:
            with Codex() as client:
                response = client.thread_list(cwd=self.cwd, limit=limit)
        except Exception as exc:
            _raise_known_sdk_error(exc)
            raise
        rows = _items(response, "data", "threads", "items")
        threads = []
        for row in rows:
            thread_id = str(_value(row, "id", "thread_id", default="?"))
            name = str(_value(row, "name", "title", "preview", default="Untitled"))
            name = " ".join(name.split())[:64] or "Untitled"
            threads.append({"id": thread_id, "name": name})
        return threads

    def read_thread(
        self,
        thread_id: str,
        model: str | None = None,
        sandbox: str = "write",
    ) -> list[dict[str, str]]:
        if not self.is_available() or not thread_id:
            return []
        from openai_codex import Codex

        try:
            with Codex() as client:
                kwargs: dict[str, Any] = {"cwd": self.cwd, "sandbox": self._sandbox(sandbox)}
                if model:
                    kwargs["model"] = model
                thread = client.thread_resume(thread_id, **kwargs)
                response = thread.read(include_turns=True)
        except Exception as exc:
            _raise_known_sdk_error(exc)
            raise
        return _history_messages(response)

    def ask(
        self,
        prompt: str,
        thread_id: str | None,
        model: str | None = None,
        effort: str = "medium",
        sandbox: str = "write",
    ) -> CodexAskResult:
        from openai_codex import Codex

        try:
            with Codex() as client:
                kwargs: dict[str, Any] = {"cwd": self.cwd, "sandbox": self._sandbox(sandbox)}
                if model:
                    kwargs["model"] = model
                if thread_id:
                    thread = client.thread_resume(thread_id, **kwargs)
                else:
                    thread = client.thread_start(**kwargs)

                turn_kwargs: dict[str, Any] = {
                    "cwd": self.cwd,
                    "effort": effort,
                    "sandbox": self._sandbox(sandbox),
                }
                if model:
                    turn_kwargs["model"] = model
                result = thread.turn(prompt, **turn_kwargs).run()
        except Exception as exc:
            _raise_known_sdk_error(exc)
            raise
        if result.final_response:
            return CodexAskResult(thread_id=str(thread.id), reply=result.final_response)
        if result.error:
            raise RuntimeError(str(result.error))
        raise RuntimeError(f"Turn ended without final response: {result.status}")
