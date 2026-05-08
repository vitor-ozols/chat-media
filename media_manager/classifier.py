from __future__ import annotations

import re

from .gemini import DEFAULT_MODEL, generate_reply


MOVIE_HINTS = {
    "1080p",
    "2160p",
    "720p",
    "bluray",
    "brrip",
    "dvdrip",
    "web-dl",
    "webrip",
    "x264",
    "x265",
    "hdrip",
    "movie",
    "film",
    "episode",
    "season",
    "s01",
    "s02",
}
MUSIC_HINTS = {
    "mp3",
    "flac",
    "album",
    "discography",
    "single",
    "ep",
    "track",
    "lossless",
    "320kbps",
    "music",
    "ost",
}


def classify_media(label: str, api_key: str | None = None, model: str | None = None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", label.lower())
    tokens = set(normalized.split())

    if tokens & MOVIE_HINTS:
        return "movie"
    if tokens & MUSIC_HINTS:
        return "music"

    if any(ext in normalized for ext in (".mp3", ".flac", ".wav", ".aac", ".m4a")):
        return "music"
    if any(ext in normalized for ext in (".mkv", ".mp4", ".avi", ".mov")):
        return "movie"

    if api_key:
        result = generate_reply(
            [
                {
                    "role": "user",
                    "content": (
                        "Classifique a midia abaixo como `music`, `movie` ou `unknown`. "
                        "Responda com apenas uma palavra.\n\n"
                        f"Entrada: {label}"
                    ),
                }
            ],
            model=model or DEFAULT_MODEL,
            api_key=api_key,
        ).strip().lower()
        if result in {"music", "movie", "unknown"}:
            return result

    return "movie"
