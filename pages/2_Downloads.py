from __future__ import annotations

from api_server import ensure_api_server
from media_manager.service import get_media_service
from torrent_manager.ui import render_page
from ui_shell import configure_page


configure_page("Torrents", "Adicione, acompanhe e gerencie downloads BitTorrent em um só lugar.")

media_service = get_media_service()
ensure_api_server(media_service)
render_page(media_service.torrent_service)
