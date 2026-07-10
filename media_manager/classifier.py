from __future__ import annotations

import re

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
    "s03",
    "s04",
    "s05",
    "s06",
    "hdtv",
    "remux",
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
    "discografia",
    "ao vivo",
}


def classify_media(label: str) -> str:
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

    return "movie"
