from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


CODEX_COMMANDS = {
    "/help": "Mostra os comandos disponiveis neste app.",
    "/status": "Mostra disponibilidade do Codex CLI/SDK e resumo dos downloads.",
    "/models": "Lista os modelos retornados pelo Codex SDK.",
    "/model ID": "Troca o modelo atual do chat.",
    "/effort low|medium|high": "Troca o effort atual do chat.",
    "/sandbox read|write|full": "Troca o nivel de acesso do Codex dentro do container.",
    "/threads": "Lista as ultimas threads do Codex.",
    "/resume THREAD_ID": "Retoma uma thread existente do Codex.",
    "/new": "Inicia um novo chat.",
}


@dataclass(frozen=True, slots=True)
class CodexRuntimeStatus:
    available: bool
    executable: str | None
    version: str | None
    auth_hint: str


class CodexRuntime:
    def status(self) -> CodexRuntimeStatus:
        executable = shutil.which("codex")
        if not executable:
            return CodexRuntimeStatus(
                available=False,
                executable=None,
                version=None,
                auth_hint="`codex` nao foi encontrado no PATH do processo Streamlit.",
            )

        version = None
        try:
            result = subprocess.run(
                [executable, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = (result.stdout or result.stderr).strip() or None
        except Exception as exc:
            version = f"Falha ao consultar versao: {exc}"

        auth_hint = (
            "Autenticacao do Codex disponivel no ambiente."
            if os.getenv("OPENAI_API_KEY")
            else "Autenticacao do Codex depende do ambiente atual."
        )
        return CodexRuntimeStatus(
            available=True,
            executable=executable,
            version=version,
            auth_hint=auth_hint,
        )

    def render_status(self) -> str:
        status = self.status()
        if not status.available:
            return (
                "Codex SDK/CLI: indisponivel.\n"
                f"- Motivo: {status.auth_hint}\n"
                "- A API de downloads e o cliente BitTorrent continuam independentes do Codex."
            )
        return (
            "Codex SDK/CLI: disponivel.\n"
            f"- Executavel: `{status.executable}`\n"
            f"- Versao: `{status.version or 'nao informada'}`\n"
            f"- Autenticacao: {status.auth_hint}"
        )

    @staticmethod
    def command_help() -> str:
        lines = ["Comandos slash disponiveis:"]
        for command, description in CODEX_COMMANDS.items():
            lines.append(f"- `{command}`: {description}")
        return "\n".join(lines)
