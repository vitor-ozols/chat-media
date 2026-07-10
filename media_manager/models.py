from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from torrent_manager.utils import utc_now


@dataclass(slots=True)
class DownloadRecord:
    id: str
    source_kind: str
    source_value: str
    display_name: str
    media_type: str
    status: str
    target_path: str
    external_id: str | None = None
    progress: float = 0.0
    details_json: str = "{}"
    error_message: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def copy(self, **changes: Any) -> "DownloadRecord":
        payload = self.to_dict()
        payload.update(changes)
        return DownloadRecord(**payload)


@dataclass(slots=True)
class ChatMessageRecord:
    id: int | None
    session_id: str
    role: str
    content: str
    model: str | None
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ChatSessionRecord:
    id: str
    title: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
