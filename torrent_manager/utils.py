from __future__ import annotations

from datetime import datetime, timezone


STATUS_LABELS = {
    "queued": "Na fila",
    "fetching_metadata": "Buscando metadados",
    "checking": "Verificando",
    "downloading": "Baixando",
    "seeding": "Semeando",
    "paused": "Pausado",
    "completed": "Concluido",
    "error": "Erro",
    "removed": "Removido",
}

STATUS_CLASSES = {
    "queued": "status-queued",
    "fetching_metadata": "status-meta",
    "checking": "status-checking",
    "downloading": "status-downloading",
    "seeding": "status-seeding",
    "paused": "status-paused",
    "completed": "status-completed",
    "error": "status-error",
    "removed": "status-removed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


def format_rate(value: int | float | None) -> str:
    if not value:
        return "0 B/s"
    return f"{format_bytes(value)}/s"


def format_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    if seconds < 60:
        return f"{seconds}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remaining}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def format_timestamp(value: str | None) -> str:
    timestamp = parse_iso(value)
    if not timestamp:
        return "-"
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def status_label(status: str) -> str:
    return STATUS_LABELS.get(str(status), str(status))


def status_css_class(status: str) -> str:
    return STATUS_CLASSES.get(str(status), "status-queued")

