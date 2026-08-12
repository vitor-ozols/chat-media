from __future__ import annotations

import os
import re
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


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()
    return obj


def _unwrap_root(obj: Any) -> Any:
    obj = _dump(obj)
    while isinstance(obj, dict) and set(obj) == {"root"}:
        obj = obj["root"]
    return obj


def _text_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _history_messages(response: Any) -> list[dict[str, str]]:
    dumped = _dump(response)
    thread = _value(dumped, "thread", default=dumped)
    messages: list[dict[str, str]] = []
    for turn in _items(thread, "turns"):
        assistant_candidates: list[tuple[str, str]] = []
        for item in _items(turn, "items"):
            item = _unwrap_root(item)
            kind = _value(item, "type")
            if kind == "userMessage":
                chunks = []
                for content in _items(item, "content"):
                    content = _unwrap_root(content)
                    text = _value(content, "text")
                    if text:
                        chunks.append(str(text))
                if chunks:
                    messages.append({"role": "user", "content": "\n".join(chunks)})
            elif kind == "agentMessage":
                raw_phase = _value(item, "phase", default="")
                phase = str(getattr(raw_phase, "value", raw_phase) or "")
                text = _value(item, "text")
                if text:
                    assistant_candidates.append((phase, str(text)))
        final_answers = [text for phase, text in assistant_candidates if phase.endswith("final_answer")]
        if final_answers:
            messages.append({"role": "assistant", "content": final_answers[-1]})
        elif assistant_candidates:
            # Older runtimes did not persist the message phase. The final agent
            # message in a completed turn is the best available representation.
            messages.append({"role": "assistant", "content": assistant_candidates[-1][1]})
    return messages


def _skill_name(skill_file: Path) -> str:
    try:
        head = skill_file.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return skill_file.parent.name
    match = re.search(r"(?m)^name:\s*[\"']?([^\n\"']+)", head)
    return match.group(1).strip() if match else skill_file.parent.name


def _skill_roots(cwd: Path) -> list[Path]:
    roots: list[Path] = []
    current = cwd.resolve()
    while True:
        roots.append(current / ".agents" / "skills")
        if current.parent == current:
            break
        current = current.parent

    home = Path.home()
    roots.extend(
        [
            home / ".agents" / "skills",
            home / ".codex" / "skills",
            Path("/etc/codex/skills"),
        ]
    )
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        roots.append(Path(codex_home).expanduser() / "skills")
    return roots


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
    def _client():
        from openai_codex import Codex, CodexConfig

        codex_bin = os.environ.get("CODEX_BIN")
        if codex_bin and Path(codex_bin).is_file():
            return Codex(CodexConfig(codex_bin=codex_bin))
        return Codex()

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
        try:
            with self._client() as client:
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
                    "default_effort": _text_value(
                        _value(row, "default_reasoning_effort", default="medium")
                    ),
                    "efforts": [
                        _text_value(_value(option, "reasoning_effort", default=option))
                        for option in _items(row, "supported_reasoning_efforts")
                    ],
                }
            )
        return models

    def list_skills(self) -> list[dict[str, str]]:
        found: dict[str, str] = {}
        visited: set[Path] = set()
        for root in _skill_roots(Path(self.cwd)):
            try:
                resolved = root.resolve()
            except OSError:
                resolved = root
            if resolved in visited or not root.is_dir():
                continue
            visited.add(resolved)
            try:
                skill_files = root.rglob("SKILL.md")
                for skill_file in skill_files:
                    name = _skill_name(skill_file)
                    found.setdefault(name, str(skill_file.resolve()))
            except OSError:
                continue
        return [{"name": name, "path": path} for name, path in sorted(found.items())]

    def list_threads(
        self,
        limit: int = 20,
        model: str | None = None,
        sandbox: str = "write",
    ) -> list[dict[str, str]]:
        if not self.is_available():
            return []
        try:
            with self._client() as client:
                # Do not filter by cwd: the mounted Codex home contains useful
                # conversations created by the machine in other workspaces.
                response = client.thread_list(limit=limit)
        except Exception as exc:
            _raise_known_sdk_error(exc)
            raise
        rows = _items(response, "data", "threads", "items")
        threads = []
        for row in rows:
            thread_id = str(_value(row, "id", "thread_id", default="?"))
            name = str(_value(row, "name", "title", "preview", default="Untitled"))
            name = " ".join(name.split())[:64] or "Untitled"
            threads.append(
                {
                    "id": thread_id,
                    "name": name,
                    "preview": str(_value(row, "preview", default="")),
                    "updated_at": str(_value(row, "updated_at", default="")),
                }
            )
        return threads

    def read_thread(
        self,
        thread_id: str,
        model: str | None = None,
        sandbox: str = "write",
    ) -> list[dict[str, str]]:
        if not self.is_available() or not thread_id:
            return []
        try:
            with self._client() as client:
                # Reading directly avoids acquiring a writer, so even a thread
                # currently open in Codex can be displayed in History.
                response = client._client.thread_read(thread_id, include_turns=True)
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
        from openai_codex import SkillInput, TextInput

        try:
            with self._client() as client:
                kwargs: dict[str, Any] = {"cwd": self.cwd, "sandbox": self._sandbox(sandbox)}
                if model:
                    kwargs["model"] = model
                if thread_id:
                    try:
                        thread = client.thread_resume(thread_id, **kwargs)
                    except Exception as exc:
                        if "active writer" not in str(exc).lower():
                            raise
                        # A conversation open in another Codex process cannot
                        # acquire a second writer. Fork it so the user can keep
                        # the full context without interrupting that process.
                        thread = client.thread_fork(thread_id, **kwargs)
                else:
                    thread = client.thread_start(**kwargs)

                turn_kwargs: dict[str, Any] = {
                    "cwd": self.cwd,
                    "effort": effort,
                    "sandbox": self._sandbox(sandbox),
                }
                if model:
                    turn_kwargs["model"] = model
                skills = {item["name"]: item["path"] for item in self.list_skills()}
                mentioned = []
                for name in re.findall(r"(?<![\w$])\$([A-Za-z0-9_-]+)", prompt):
                    if name in skills and name not in mentioned:
                        mentioned.append(name)
                run_input: Any = prompt
                if mentioned:
                    run_input = [
                        *(SkillInput(name=name, path=skills[name]) for name in mentioned),
                        TextInput(prompt),
                    ]
                result = thread.run(run_input, **turn_kwargs)
        except Exception as exc:
            _raise_known_sdk_error(exc)
            raise
        if result.final_response:
            return CodexAskResult(thread_id=str(thread.id), reply=result.final_response)
        if result.error:
            raise RuntimeError(str(result.error))
        raise RuntimeError(f"Turn ended without final response: {result.status}")
