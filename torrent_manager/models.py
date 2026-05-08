from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .utils import utc_now


class SourceType(StrEnum):
    MAGNET = "magnet"
    TORRENT_FILE = "torrent_file"


class TorrentStatus(StrEnum):
    QUEUED = "queued"
    FETCHING_METADATA = "fetching_metadata"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    SEEDING = "seeding"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    REMOVED = "removed"


ACTIVE_STATUSES = {
    TorrentStatus.QUEUED,
    TorrentStatus.FETCHING_METADATA,
    TorrentStatus.CHECKING,
    TorrentStatus.DOWNLOADING,
    TorrentStatus.SEEDING,
}


@dataclass(slots=True)
class TorrentRecord:
    id: str
    name: str
    source_type: str
    source_value: str
    download_dir: str
    torrent_file_path: str | None = None
    info_hash: str | None = None
    status: str = TorrentStatus.QUEUED
    progress: float = 0.0
    total_size: int = 0
    downloaded: int = 0
    uploaded: int = 0
    download_rate: int = 0
    upload_rate: int = 0
    peers: int = 0
    seeds: int = 0
    ratio: float = 0.0
    eta_seconds: int | None = None
    metadata_ready: bool = False
    file_count: int = 0
    resume_data: bytes | None = None
    error_message: str | None = None
    added_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def copy(self, **changes: Any) -> "TorrentRecord":
        payload = self.to_dict()
        payload.update(changes)
        return TorrentRecord(**payload)


@dataclass(slots=True)
class EventRecord:
    id: int | None
    torrent_id: str | None
    torrent_name: str | None
    level: str
    message: str
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class TorrentFileRecord:
    path: str
    size: int
    downloaded: int
    progress: float


@dataclass(slots=True)
class EngineSnapshot:
    available: bool
    message: str
    download_rate: int = 0
    upload_rate: int = 0
    peers: int = 0
    dht_nodes: int = 0
    has_incoming_connections: bool = False

