from __future__ import annotations

from fastapi import APIRouter

from app import state
from app.genres import DEFAULT_GENRES

router = APIRouter(prefix="/api/library", tags=["config"])


@router.get("/{library_id}/config")
def get_config(library_id: str):
    config = state.get_config(library_id)
    return {
        "genres": config.genres,
        "default_genres": DEFAULT_GENRES,
        "genre_redirects": config.genre_redirects,
        "artist_overrides": config.artist_overrides,
    }
