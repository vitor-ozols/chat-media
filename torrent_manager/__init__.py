from .config import AppPaths, ensure_app_paths

__all__ = ["AppPaths", "TorrentService", "ensure_app_paths"]


def __getattr__(name: str):
    if name == "TorrentService":
        from .service import TorrentService

        return TorrentService
    raise AttributeError(name)

