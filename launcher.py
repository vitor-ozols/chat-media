from __future__ import annotations

import os

from streamlit.web import bootstrap

from api_server import ensure_api_server
from media_manager.service import get_media_service


def main() -> None:
    streamlit_options = {
        "server_baseUrlPath": os.environ.get("STREAMLIT_SERVER_BASE_URL_PATH", "torrent")
    }
    bootstrap.load_config_options(streamlit_options)
    service = get_media_service()
    ensure_api_server(service)
    bootstrap.run(
        "app.py",
        False,
        [],
        streamlit_options,
    )


if __name__ == "__main__":
    main()
