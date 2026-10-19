from __future__ import annotations

import os

from waitress import serve

from api_server import ensure_api_server
from api import create_app
from media_manager.service import get_media_service


def main() -> None:
    service = get_media_service()
    app = create_app(service=service)
    ui_port = int(os.environ.get("PORT", "8501"))
    if ui_port != int(os.environ.get("API_PORT", "5000")):
        ensure_api_server(service, app=app)
    serve(app, host=os.environ.get("HOST", "0.0.0.0"), port=ui_port, threads=12,
          channel_timeout=120, max_request_body_size=20 * 1024 * 1024)


if __name__ == "__main__":
    main()
