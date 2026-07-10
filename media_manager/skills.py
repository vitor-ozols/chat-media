from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaSkill:
    name: str
    title: str
    description: str
    examples: tuple[str, ...]
    source: str = "local"


SKILLS: tuple[MediaSkill, ...] = (
    MediaSkill(
        name="youtube_music",
        title="Baixar musica do YouTube",
        description="Recebe URL de video ou playlist, baixa audio com yt-dlp e organiza em artista/album/faixa.",
        examples=(
            "baixa https://www.youtube.com/watch?v=...",
            "baixa a playlist inteira https://www.youtube.com/playlist?list=...",
            "artista: Nome, album: Album, musica: Faixa",
        ),
    ),
    MediaSkill(
        name="torrent_download",
        title="Baixar torrent com acompanhamento",
        description="Recebe magnet ou .torrent, adiciona ao libtorrent e expõe progresso, peers, seeds, ETA e eventos.",
        examples=(
            "magnet:?xt=urn:btih:...",
            "anexe um arquivo .torrent no chat",
            "acompanhe detalhes na pagina Downloads",
        ),
    ),
    MediaSkill(
        name="download_status",
        title="Status dos downloads",
        description="Consulta a fila local antes de responder sobre progresso, erros ou itens aguardando metadados.",
        examples=("qual o status?", "terminou?", "/downloads"),
    ),
    MediaSkill(
        name="codex_cli",
        title="Comandos Codex",
        description="Expõe comandos slash principais do app e status do Codex CLI/SDK disponível no ambiente.",
        examples=("/status", "/help", "/skills", "/new"),
    ),
    MediaSkill(
        name="gws-cli",
        title="Google Workspace CLI",
        description="Skill global do Codex para Gmail, Drive, Calendar, Sheets, Docs e diagnostico de auth via `gws`.",
        examples=("consultar agenda", "buscar emails", "criar/ler planilhas"),
        source="global",
    ),
    MediaSkill(
        name="pointbot-orcamentos",
        title="Orcamentos Point Viagens",
        description=(
            "Skill global do Codex para cotacoes da Point Viagens: busca na plataforma, "
            "comparacao de opcoes, HTML/PDF, carrinho/checkout e email com confirmacao."
        ),
        examples=("orcamento Point para Orlando", "gerar cotacao HTML", "enviar cotacao por email apos confirmar"),
        source="global",
    ),
)


def render_skills() -> str:
    lines = ["Skills registradas neste projeto:"]
    for skill in [item for item in SKILLS if item.source == "local"]:
        lines.append(f"- `{skill.name}`: {skill.title}. {skill.description}")
    global_skills = [item for item in SKILLS if item.source == "global"]
    if global_skills:
        lines.append("")
        lines.append("Skills globais do Codex tambem disponiveis neste projeto:")
        for skill in global_skills:
            lines.append(f"- `{skill.name}`: {skill.title}. {skill.description}")
    return "\n".join(lines)
