from __future__ import annotations

import os
import threading

from werkzeug.serving import make_server

from api import create_app


_lock = threading.Lock()
_server = None
_thread = None


def ensure_api_server(service, app=None) -> None:
    """Start the compatibility API once, sharing the web app's download engines."""
    global _server, _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        port = int(os.environ.get("API_PORT", "5000"))
        _server = make_server("0.0.0.0", port, app or create_app(service=service), threaded=True)
        _thread = threading.Thread(target=_server.serve_forever, name="downloads-api", daemon=True)
        _thread.start()
