from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaPaths:
    root: Path
    data_dir: Path
    media_dir: Path
    music_dir: Path
    movies_dir: Path
    youtube_dir: Path
    db_path: Path


def ensure_media_paths(root: Path) -> MediaPaths:
    root = root.resolve()
    data_dir = root / "data"
    media_dir = root / "media"
    music_dir = media_dir / "music"
    movies_dir = media_dir / "movies"
    youtube_dir = data_dir / "youtube"
    db_path = data_dir / "media.db"

    for path in (data_dir, media_dir, music_dir, movies_dir, youtube_dir):
        path.mkdir(parents=True, exist_ok=True)

    return MediaPaths(
        root=root,
        data_dir=data_dir,
        media_dir=media_dir,
        music_dir=music_dir,
        movies_dir=movies_dir,
        youtube_dir=youtube_dir,
        db_path=db_path,
    )
