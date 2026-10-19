"""One-time, non-destructive import into a dedicated Codex home.

The damaged history projection is deliberately NOT copied. Codex creates a new
database; session rollouts remain available to the app's read-only fallback.
Source databases are opened read-only and never changed.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path


def import_home(source: Path, destination: Path, runtime_home: Path | None = None) -> None:
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir():
        raise ValueError("Source Codex home does not exist")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination must be separate directories")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Destination must be empty; existing state will not be overwritten")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime_home = runtime_home or destination
    for name in ("auth.json", "config.toml", "models_cache.json", "session_index.jsonl",
                 "history.jsonl", "sessions", "archived_sessions", "skills", "rules", "plugins"):
        item = source / name
        if item.is_dir():
            shutil.copytree(item, destination / name, symlinks=True)
        elif item.is_file():
            shutil.copy2(item, destination / name)
    for database in source.glob("state_*.sqlite"):
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as original:
            with sqlite3.connect(destination / database.name) as copied:
                original.backup(copied)
                if copied.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise RuntimeError("The source thread index is also corrupted")
                # Rollouts created on the host may contain its absolute path.
                for thread_id, raw_path in copied.execute("SELECT id, rollout_path FROM threads").fetchall():
                    path = Path(raw_path)
                    for folder in ("sessions", "archived_sessions"):
                        if folder in path.parts:
                            offset = path.parts.index(folder)
                            relative = Path(*path.parts[offset:])
                            if (destination / relative).is_file():
                                copied.execute("UPDATE threads SET rollout_path=? WHERE id=?",
                                               (str(runtime_home / relative), thread_id))
                            break


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--runtime-home", type=Path,
                        help="Absolute Codex home path inside the deployed container")
    args = parser.parse_args()
    import_home(args.source, args.destination, args.runtime_home)
    print("Imported sessions and thread index; Codex will create a fresh history database.")


if __name__ == "__main__":
    main()
