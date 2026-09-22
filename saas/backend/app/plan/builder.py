"""
Construction du plan d'organisation proposé — jamais appliqué sans
confirmation explicite (voir PROJECT_CONTEXT.md §12/§14/§24).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.classification.pipeline import ClassificationStats, TrackClassification
from app.plan.config import GenreConfig


@dataclass
class PlaylistChange:
    genre: str
    track_ids: list[str]
    already_exists: bool = False

    @property
    def nb_tracks(self) -> int:
        return len(self.track_ids)


@dataclass
class OrganizationPlan:
    changes: list[PlaylistChange] = field(default_factory=list)
    nb_tracks_total: int = 0
    nb_artists_total: int = 0
    nb_known_from_db: int = 0
    nb_researched: int = 0

    def to_dict(self) -> dict:
        return {
            "summary": {
                "nb_tracks": self.nb_tracks_total,
                "nb_artists": self.nb_artists_total,
                "nb_known_from_db": self.nb_known_from_db,
                "nb_researched": self.nb_researched,
            },
            "changes": [
                {
                    "action": "create_playlist" if not c.already_exists else "reuse_playlist",
                    "name": c.genre,
                    "nb_tracks": c.nb_tracks,
                    "track_ids": c.track_ids,
                }
                for c in self.changes
            ],
        }


def build_plan(
    classified_tracks: list[TrackClassification],
    config: GenreConfig,
    stats: ClassificationStats,
    existing_playlist_names: set[str] | None = None,
) -> OrganizationPlan:
    """Regroupe les morceaux classifiés par genre effectif (après
    redirections/overrides de `config`) en un plan prévisualisable."""
    existing = {n.strip().lower() for n in (existing_playlist_names or set())}

    par_genre: dict[str, list[str]] = {}
    for t in classified_tracks:
        genre_effectif = config.resolve_genre(t.primary_artist, t.primary_genre)
        par_genre.setdefault(genre_effectif, []).append(t.track_id)

    changes = [
        PlaylistChange(genre=genre, track_ids=track_ids, already_exists=genre.strip().lower() in existing)
        for genre, track_ids in sorted(par_genre.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]

    return OrganizationPlan(
        changes=changes,
        nb_tracks_total=stats.nb_tracks,
        nb_artists_total=stats.nb_unique_artists,
        nb_known_from_db=stats.nb_known_from_db,
        nb_researched=stats.nb_researched,
    )
