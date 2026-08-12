#!/usr/bin/env python3
"""Cliente sem dependências externas para a API local do chat-media."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:5000"


def request_json(base_url: str, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"não foi possível acessar {base_url}: {exc.reason}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cliente da API de downloads do chat-media")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("CHAT_MEDIA_API_URL", DEFAULT_BASE_URL),
        help="URL base da API (padrão: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("health", help="verificar a API e o motor torrent")
    subparsers.add_parser("list", help="listar downloads")

    get_parser = subparsers.add_parser("get", help="consultar um download")
    get_parser.add_argument("id", help="ID do download ou ID externo do torrent")

    add_parser = subparsers.add_parser("add", help="cadastrar um download")
    add_parser.add_argument("--url", action="append", required=True, dest="urls", help="magnet ou URL do YouTube; repetir para várias")
    add_parser.add_argument("--final-path", required=True, help="arquivo ou diretório final visível pelo serviço")
    add_parser.add_argument("--start-paused", action="store_true", help="cadastrar torrent pausado")
    add_parser.add_argument("--playlist", action="store_true", help="tratar URL do YouTube como playlist")
    add_parser.add_argument("--artist", help="metadado de artista")
    add_parser.add_argument("--album", help="metadado de álbum")
    add_parser.add_argument("--title", help="metadado de título")
    add_parser.add_argument("--metadata-json", help="objeto JSON adicional de metadados")
    add_parser.add_argument("--dry-run", action="store_true", help="mostrar o payload sem enviar")
    return parser


def add_payload(args: argparse.Namespace) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if args.metadata_json:
        parsed = json.loads(args.metadata_json)
        if not isinstance(parsed, dict):
            raise ValueError("--metadata-json deve ser um objeto JSON")
        metadata.update(parsed)
    metadata.update({key: value for key, value in {
        "artist": args.artist,
        "album": args.album,
        "title": args.title,
    }.items() if value})
    payload: dict[str, Any] = {
        "urls": args.urls,
        "final_path": args.final_path,
        "start_paused": args.start_paused,
        "playlist": args.playlist,
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "health":
            result = request_json(args.base_url, "/health")
        elif args.command == "list":
            result = request_json(args.base_url, "/downloads")
        elif args.command == "get":
            from urllib.parse import quote
            result = request_json(args.base_url, f"/downloads/{quote(args.id, safe='')}")
        else:
            payload = add_payload(args)
            result = payload if args.dry_run else request_json(args.base_url, "/downloads", "PUT", payload)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
