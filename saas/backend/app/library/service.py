"""LibraryService — orchestration haut niveau (voir ARCHITECTURE.md §2) :
relie LibraryProvider, le pipeline de classification et le plan builder.
Séparé des routes pour rester testable sans FastAPI."""

from __future__ import annotations

from dataclasses import dataclass

from app.classification.db_repo import ArtistClassificationRepo
from app.classification.pipeline import ClassificationRunResult, TrackArtistInput, classify_library
from app.classification.research import ArtistResearcher
from app.library.provider import LibraryProvider
from app.plan.builder import OrganizationPlan, build_plan
from app.plan.config import GenreConfig


@dataclass
class AnalysisResult:
    classification: ClassificationRunResult
    plan: OrganizationPlan


def analyze_library(
    provider: LibraryProvider,
    repo: ArtistClassificationRepo,
    researcher: ArtistResearcher,
    config: GenreConfig,
) -> AnalysisResult:
    """Pipeline complet lecture -> classification -> plan, en lecture
    seule (aucune écriture sur la bibliothèque — voir apply.apply_plan
    pour la seule fonction qui écrit réellement)."""
    tracks = provider.list_tracks()
    inputs = [TrackArtistInput(track_id=t.track_id, raw_artist_field=t.raw_artist_field, title=t.title) for t in tracks]

    classification = classify_library(inputs, repo, researcher)

    existing_names = {p.name for p in provider.list_playlists()}
    plan = build_plan(classification.tracks, config, classification.stats, existing_playlist_names=existing_names)

    return AnalysisResult(classification=classification, plan=plan)
