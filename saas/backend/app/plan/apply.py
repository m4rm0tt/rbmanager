"""
Application d'un plan confirmé — la SEULE fonction du produit qui écrit
réellement sur la bibliothèque (voir PROJECT_CONTEXT.md §14/§24).
Jamais appelée directement par le chat ou l'analyse : seulement après
confirmation explicite de l'utilisateur (`[Apply Changes]`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.library.provider import LibraryProvider
from app.plan.builder import OrganizationPlan


@dataclass
class ApplyResult:
    backup_path: Path
    playlists_created: list[str] = field(default_factory=list)
    playlists_reused: list[str] = field(default_factory=list)
    nb_tracks_moved: int = 0


def apply_plan(plan: OrganizationPlan, provider: LibraryProvider, parent_folder_id: str | None = None) -> ApplyResult:
    """Sauvegarde une fois, crée/réutilise les playlists nécessaires,
    ajoute les morceaux (idempotent), puis persiste une seule fois."""
    backup_path = provider.backup()

    created: list[str] = []
    reused: list[str] = []
    nb_moved = 0

    for change in plan.changes:
        existing = provider.find_playlist_by_name(change.genre, parent_id=parent_folder_id)
        if existing is not None:
            playlist_id = existing.id
            reused.append(change.genre)
        else:
            playlist_id = provider.create_playlist(change.genre, parent_id=parent_folder_id)
            created.append(change.genre)

        for track_id in change.track_ids:
            provider.add_track(playlist_id, track_id)
            nb_moved += 1

    provider.save()
    return ApplyResult(backup_path=backup_path, playlists_created=created, playlists_reused=reused, nb_tracks_moved=nb_moved)
