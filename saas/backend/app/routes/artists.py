"""Page Artists — gérer la Artist Classification Database (PROJECT_CONTEXT.md §21-22-23)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import state
from app.normalization import normalize_artist_name

router = APIRouter(prefix="/api/artists", tags=["artists"])


@router.get("")
def list_artists(search: str | None = None, genre: str | None = None):
    records = state.classification_repo.list_all(search=search, genre=genre)
    return {"artists": [r.to_dict() for r in records], "total": len(records)}


class ArtistUpdate(BaseModel):
    primary_genre: str | None = None
    confidence: float | None = None


@router.patch("/{normalized_artist_name}")
def update_artist(normalized_artist_name: str, body: ArtistUpdate):
    existant = state.classification_repo.get(normalized_artist_name)
    if existant is None:
        raise HTTPException(404, "Artiste introuvable.")

    record = state.classification_repo.upsert(
        artist_name=existant.artist_name,
        normalized_artist_name=normalized_artist_name,
        primary_genre=body.primary_genre or existant.primary_genre,
        genres=existant.genres,
        confidence=body.confidence if body.confidence is not None else existant.confidence,
        source="manual",
    )
    return record.to_dict()


@router.delete("/{normalized_artist_name}")
def delete_artist(normalized_artist_name: str):
    if not state.classification_repo.delete(normalized_artist_name):
        raise HTTPException(404, "Artiste introuvable.")
    return {"deleted": True}


class ArtistCorrection(BaseModel):
    """Corps de la correction manuelle décrite au §23 : 'Do you want to
    apply this classification to all <artist> tracks and save it to the
    global artist database?'"""

    artist_name: str
    new_genre: str
    remember_globally: bool = True
    library_id: str | None = None


@router.post("/correct")
def correct_artist(body: ArtistCorrection):
    cle = normalize_artist_name(body.artist_name)
    if body.remember_globally:
        state.classification_repo.upsert(
            artist_name=body.artist_name,
            normalized_artist_name=cle,
            primary_genre=body.new_genre,
            genres=[body.new_genre],
            confidence=1.0,
            source="manual",
        )
        return {"scope": "global", "artist_name": body.artist_name, "new_genre": body.new_genre}

    if not body.library_id:
        raise HTTPException(422, "library_id requis quand remember_globally=false.")
    config = state.get_config(body.library_id)
    config.override_artist(body.artist_name, body.new_genre)
    state.set_config(body.library_id, config)
    return {"scope": "library", "library_id": body.library_id, "artist_name": body.artist_name, "new_genre": body.new_genre}
