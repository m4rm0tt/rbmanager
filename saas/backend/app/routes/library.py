from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import state
from app.library.provider import PlaylistNode
from app.library.rbmanager_adapter import UnsupportedLibraryFormatError
from app.library.service import analyze_library
from app.library.workspace import create_library_workspace, library_export_pdb_path
from app.plan.apply import apply_plan

router = APIRouter(prefix="/api/library", tags=["library"])


def _playlist_to_dict(node: PlaylistNode) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "is_folder": node.is_folder,
        "nb_tracks": node.nb_tracks,
        "children": [_playlist_to_dict(c) for c in node.children],
    }


@router.post("/upload")
async def upload_library(file: UploadFile):
    contenu = await file.read()
    library_id = create_library_workspace(state.WORKSPACE_ROOT, contenu)
    try:
        adapter = state.get_adapter(library_id)
    except UnsupportedLibraryFormatError as exc:
        raise HTTPException(422, str(exc)) from exc

    tracks = adapter.list_tracks()
    playlists = adapter.list_playlists()
    return {
        "library_id": library_id,
        "nb_tracks": len(tracks),
        "nb_playlists": len(playlists),
        "playlists": [_playlist_to_dict(p) for p in playlists],
    }


@router.get("/{library_id}/download")
def download_library(library_id: str):
    chemin = library_export_pdb_path(state.WORKSPACE_ROOT, library_id)
    if not chemin.exists():
        raise HTTPException(404, "Bibliothèque introuvable.")
    return FileResponse(chemin, filename="export.pdb", media_type="application/octet-stream")


@router.get("/{library_id}/playlists")
def get_playlists(library_id: str):
    try:
        adapter = state.get_adapter(library_id)
    except state.LibraryNotFoundError as exc:
        raise HTTPException(404, "Bibliothèque introuvable.") from exc
    return {"playlists": [_playlist_to_dict(p) for p in adapter.list_playlists()]}


@router.post("/{library_id}/analyze")
def analyze(library_id: str):
    """Analyse en LECTURE SEULE : extraction des artistes, classification,
    construction du plan proposé — n'écrit jamais sur la bibliothèque
    (voir PROJECT_CONTEXT.md §12/§24)."""
    try:
        adapter = state.get_adapter(library_id)
    except state.LibraryNotFoundError as exc:
        raise HTTPException(404, "Bibliothèque introuvable.") from exc

    config = state.get_config(library_id)
    resultat = analyze_library(adapter, state.classification_repo, state.researcher, config)
    return resultat.plan.to_dict()


@router.post("/{library_id}/apply")
def apply(library_id: str):
    """Applique le dernier plan calculé pour cette bibliothèque —
    n'écrit qu'après cet appel explicite (le frontend n'y accède
    qu'après confirmation utilisateur, voir PROJECT_CONTEXT.md §14)."""
    try:
        adapter = state.get_adapter(library_id)
    except state.LibraryNotFoundError as exc:
        raise HTTPException(404, "Bibliothèque introuvable.") from exc

    config = state.get_config(library_id)
    resultat = analyze_library(adapter, state.classification_repo, state.researcher, config)
    apply_resultat = apply_plan(resultat.plan, adapter)

    run = state.history_repo.record_run(
        library_id=library_id,
        nb_tracks=apply_resultat.nb_tracks_moved,
        playlists_created=apply_resultat.playlists_created,
        playlists_reused=apply_resultat.playlists_reused,
        backup_path=str(apply_resultat.backup_path),
    )
    return {
        "run": run.to_dict(),
        "playlists_created": apply_resultat.playlists_created,
        "playlists_reused": apply_resultat.playlists_reused,
        "nb_tracks_moved": apply_resultat.nb_tracks_moved,
    }


@router.get("/{library_id}/history")
def get_history(library_id: str):
    return {"runs": [r.to_dict() for r in state.history_repo.list_for_library(library_id)]}


@router.post("/{library_id}/history/{run_id}/undo")
def undo(library_id: str, run_id: int):
    run = state.history_repo.get(run_id)
    if run is None or run.library_id != library_id:
        raise HTTPException(404, "Organisation introuvable.")
    if run.undone:
        raise HTTPException(409, "Cette organisation a déjà été annulée.")

    try:
        adapter = state.get_adapter(library_id)
    except state.LibraryNotFoundError as exc:
        raise HTTPException(404, "Bibliothèque introuvable.") from exc

    adapter.restore_backup(run.backup_path)
    state.reload_adapter(library_id)
    state.history_repo.mark_undone(run_id)
    return {"undone": True, "run_id": run_id}
