from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    data_dir: Path
    downloads_dir: Path
    torrents_dir: Path
    resume_dir: Path
    db_path: Path


def ensure_app_paths(root: Path) -> AppPaths:
    root = root.resolve()
    data_dir = root / "data"
    downloads_dir = root / "downloads"
    torrents_dir = data_dir / "torrents"
    resume_dir = data_dir / "resume"
    db_path = data_dir / "app.db"

    for path in (data_dir, downloads_dir, torrents_dir, resume_dir):
        path.mkdir(parents=True, exist_ok=True)

    return AppPaths(
        root=root,
        data_dir=data_dir,
        downloads_dir=downloads_dir,
        torrents_dir=torrents_dir,
        resume_dir=resume_dir,
        db_path=db_path,
    )

