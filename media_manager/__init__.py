def get_media_service():
    """Import the Streamlit-backed service only when the app requests it."""
    from .service import get_media_service as _get_media_service

    return _get_media_service()

__all__ = ["get_media_service"]
