#!/usr/bin/env python3
"""Importar MP3 públicos do Internet Archive para uma biblioteca Navidrome."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "archive-org-music-skill/1.0"
INVALID_PATH = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def fetch_json(url: str) -> dict[str, Any]:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("a API não retornou um objeto JSON")
    return value


def identifier_from_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.hostname not in {"archive.org", "www.archive.org"}:
        raise ValueError("use uma URL de archive.org")
    match = re.match(r"^/(?:details|download)/([^/?#]+)", parsed.path)
    if not match:
        raise ValueError("use uma URL /details/IDENTIFIER ou /download/IDENTIFIER")
    return unquote(match.group(1))


def scalar(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def safe_name(value: str) -> str:
    cleaned = INVALID_PATH.sub("_", value).strip().rstrip(".")
    return cleaned or "Unknown"


def infer_album(title: str, artist: str, year: str) -> str:
    value = title.strip()
    if artist and value.lower().startswith(f"{artist} - ".lower()):
        value = value[len(artist) + 3:]
    if year:
        value = re.sub(rf"\s*[\[(]\s*{re.escape(year)}\s*[\])]\s*$", "", value)
    return value.strip() or title.strip()


def track_number(file: dict[str, Any]) -> int:
    raw = scalar(file.get("track"))
    match = re.search(r"\d+", raw)
    if not match:
        match = re.match(r"\s*(\d+)", scalar(file.get("name")))
    return int(match.group()) if match else 10_000


def track_title(file: dict[str, Any]) -> str:
    title = scalar(file.get("title"))
    if title:
        return title
    stem = Path(unquote(scalar(file.get("name")))).stem
    return re.sub(r"^\s*\d+\s*[. _-]+\s*", "", stem).strip() or stem


def choose_mp3s(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = [f for f in files if not f.get("private") and scalar(f.get("name")).lower().endswith(".mp3")]
    originals = [f for f in public if scalar(f.get("source")).lower() == "original"]
    chosen = originals or public
    return sorted(chosen, key=lambda f: (track_number(f), scalar(f.get("name")).casefold()))


def choose_cover(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for file in files:
        name = scalar(file.get("name"))
        stem = Path(name).stem.casefold()
        if file.get("private") or Path(name).suffix.casefold() not in {".jpg", ".jpeg"}:
            continue
        if stem in {"cover", "front", "folder"}:
            candidates.append(file)
    candidates.sort(key=lambda f: scalar(f.get("source")).lower() != "original")
    return candidates[0] if candidates else None


def remote_url(identifier: str, name: str) -> str:
    return f"https://archive.org/download/{quote(identifier, safe='')}/{quote(name, safe='/')}"


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    identifier = identifier_from_url(args.url)
    payload = fetch_json(f"https://archive.org/metadata/{quote(identifier, safe='')}")
    if payload.get("is_dark"):
        raise RuntimeError("o item não está disponível publicamente")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    files = [f for f in payload.get("files", []) if isinstance(f, dict)]
    artist = args.artist or scalar(metadata.get("creator"))
    year = args.year or scalar(metadata.get("year")) or scalar(metadata.get("date"))[:4]
    album = args.album or scalar(metadata.get("album")) or infer_album(scalar(metadata.get("title")), artist, year)
    if not artist or not album:
        raise RuntimeError("não foi possível determinar artista e álbum; use --artist e --album")
    tracks = choose_mp3s(files)
    if not tracks:
        raise RuntimeError("o item não possui MP3 público")
    width = max(2, len(str(len(tracks))))
    album_dir_name = f"{safe_name(album)} ({year})" if year else safe_name(album)
    album_dir = args.library.resolve() / safe_name(artist) / album_dir_name
    entries = []
    seen: set[Path] = set()
    for position, file in enumerate(tracks, start=1):
        number = track_number(file)
        if number == 10_000:
            number = position
        title = track_title(file)
        destination = album_dir / f"{number:0{width}d} - {safe_name(title)}.mp3"
        if destination in seen:
            raise RuntimeError(f"colisão interna no manifesto: {destination}")
        seen.add(destination)
        entries.append({
            "source": remote_url(identifier, scalar(file["name"])),
            "source_name": scalar(file["name"]),
            "destination": str(destination),
            "size": int(file.get("size") or 0),
            "track": number,
            "title": title,
        })
    cover = choose_cover(files)
    return {
        "identifier": identifier,
        "item_url": f"https://archive.org/details/{identifier}",
        "library": str(args.library.resolve()),
        "album_dir": str(album_dir),
        "artist": artist,
        "album": album,
        "year": year,
        "track_count": len(entries),
        "tracks": entries,
        "cover": None if cover is None else {
            "source": remote_url(identifier, scalar(cover["name"])),
            "source_name": scalar(cover["name"]),
            "destination": str(album_dir / "cover.jpg"),
        },
    }


def download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def tag_mp3(path: Path, manifest: dict[str, Any], track: dict[str, Any]) -> None:
    try:
        from mutagen.easyid3 import EasyID3
        from mutagen.mp3 import MP3
    except ImportError as exc:
        raise RuntimeError("mutagen é necessário para aplicar tags; instale-o ou adicione-o ao PYTHONPATH") from exc
    audio = MP3(path, ID3=EasyID3)
    if audio.tags is None:
        audio.add_tags()
    audio["title"] = [track["title"]]
    audio["artist"] = [manifest["artist"]]
    audio["albumartist"] = [manifest["artist"]]
    audio["album"] = [manifest["album"]]
    audio["tracknumber"] = [f"{track['track']}/{manifest['track_count']}"]
    audio["discnumber"] = ["1/1"]
    if manifest["year"]:
        audio["date"] = [manifest["year"]]
    audio.save(v2_version=3)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def apply_manifest(manifest: dict[str, Any]) -> None:
    album_dir = Path(manifest["album_dir"])
    destinations = [Path(t["destination"]) for t in manifest["tracks"]]
    if manifest["cover"]:
        destinations.append(Path(manifest["cover"]["destination"]))
    collisions = [str(path) for path in destinations if path.exists()]
    if collisions:
        raise RuntimeError("destinos já existem; nada foi alterado:\n" + "\n".join(collisions))
    album_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archive-org-music-", dir=str(album_dir.parent)) as staging_value:
        staging = Path(staging_value)
        staged_tracks = []
        for track in manifest["tracks"]:
            target = staging / Path(track["destination"]).name
            print(f"baixando {track['track']:02d}/{manifest['track_count']:02d}: {track['title']}", file=sys.stderr)
            download(track["source"], target)
            if track["size"] and target.stat().st_size != track["size"]:
                raise RuntimeError(f"tamanho inesperado para {track['source_name']}")
            tag_mp3(target, manifest, track)
            track["sha256"] = sha256(target)
            staged_tracks.append(target)
        staged_cover = None
        if manifest["cover"]:
            staged_cover = staging / "cover.jpg"
            download(manifest["cover"]["source"], staged_cover)
        album_dir.mkdir(parents=False, exist_ok=False)
        for staged, track in zip(staged_tracks, manifest["tracks"]):
            os.replace(staged, track["destination"])
        if staged_cover:
            os.replace(staged_cover, manifest["cover"]["destination"])


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("url", help="URL /details/ ou /download/ do Internet Archive")
    value.add_argument("--library", required=True, type=Path, help="raiz da biblioteca Navidrome")
    value.add_argument("--manifest", required=True, type=Path, help="arquivo JSON de manifesto")
    value.add_argument("--artist", help="sobrescrever artista")
    value.add_argument("--album", help="sobrescrever álbum")
    value.add_argument("--year", help="sobrescrever ano")
    value.add_argument("--apply", action="store_true", help="baixar, etiquetar e instalar o álbum")
    return value


def main() -> int:
    args = parser().parse_args()
    try:
        manifest = build_manifest(args)
        collisions = [t["destination"] for t in manifest["tracks"] if Path(t["destination"]).exists()]
        manifest["collisions"] = collisions
        manifest["status"] = "planned"
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if collisions:
            raise RuntimeError("o manifesto contém colisões; nada foi alterado")
        if args.apply:
            apply_manifest(manifest)
            manifest["status"] = "completed"
            args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
