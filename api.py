from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Flask, jsonify, request

from media_manager.service import MediaService


def _download_payload(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_type": item.source_kind,
        "url": item.source_value,
        "name": item.display_name,
        "status": str(item.status),
        "progress": round(float(item.progress), 6),
        "final_path": item.target_path,
        "torrent_id": item.external_id,
        "error": item.error_message,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "completed_at": item.completed_at,
    }


def _is_youtube_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


def create_app(service: MediaService | None = None, root: Path | None = None) -> Flask:
    app = Flask(__name__)
    media_service = service or MediaService(root or Path(os.environ.get("APP_ROOT", Path.cwd())))

    @app.get("/health")
    def health():
        engine = media_service.torrent_service.get_engine_snapshot()
        return jsonify({"status": "ok", "torrent_engine": engine.available})

    @app.get("/downloads")
    def list_downloads():
        return jsonify({"downloads": [_download_payload(item) for item in media_service.list_downloads()]})

    @app.get("/downloads/<download_id>")
    def get_download(download_id: str):
        media_service.sync_downloads()
        item = media_service.db.get_download(download_id)
        if item is None:
            item = next(
                (row for row in media_service.db.list_downloads() if row.external_id == download_id),
                None,
            )
        if item is None:
            return jsonify({"error": "download não encontrado"}), 404
        return jsonify(_download_payload(item))

    @app.put("/downloads")
    def add_download():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "envie um objeto JSON"}), 400

        raw_urls = payload.get("urls")
        if raw_urls is None:
            raw_urls = [payload.get("url")]
        if not isinstance(raw_urls, list):
            return jsonify({"error": "'urls' deve ser uma lista"}), 400

        urls = [str(value).strip() for value in raw_urls if value and str(value).strip()]
        final_path = str(payload.get("final_path") or "").strip()
        if not urls:
            return jsonify({"error": "informe 'url' ou 'urls'"}), 400
        if not final_path:
            return jsonify({"error": "informe 'final_path'"}), 400

        invalid = [url for url in urls if not url.startswith("magnet:?") and not _is_youtube_url(url)]
        if invalid:
            return jsonify({"error": f"URL não suportada: {invalid[0]}"}), 400

        resolved_path = Path(final_path).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = media_service.paths.root / resolved_path
        final_path = str(resolved_path.resolve())

        created = []
        for url in urls:
            if url.startswith("magnet:?"):
                record = media_service.add_torrent_from_magnet(
                    url,
                    final_path=final_path,
                    start_paused=bool(payload.get("start_paused", False)),
                )
                item = next(
                    row for row in media_service.db.list_downloads() if row.external_id == record.id
                )
            elif _is_youtube_url(url):
                item = media_service.enqueue_youtube(
                    url,
                    metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                    treat_as_playlist=bool(payload.get("playlist", False)),
                    final_path=final_path,
                )
            created.append(_download_payload(item))

        return jsonify({"downloads": created}), 201

    from web import register_web

    register_web(app, media_service)
    return app


if __name__ == "__main__":
    create_app().run(
        host="0.0.0.0",
        port=int(os.environ.get("API_PORT", "5000")),
        threaded=True,
    )
