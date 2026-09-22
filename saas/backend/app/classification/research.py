"""
Recherche d'un artiste inconnu (voir ARCHITECTURE.md §5,
PROJECT_CONTEXT.md §7 et §"Décisions prises pendant l'implémentation").

`ArtistResearcher` est le SEUL point de contact entre le pipeline de
classification et "le monde extérieur". Le pipeline ne sait rien de son
implémentation : il l'appelle une fois par artiste inconnu (jamais par
morceau, voir `pipeline.py`) et persiste le résultat. C'est ce qui
permet de brancher plus tard un vrai moteur (recherche web, appel à un
LLM, base tierce type MusicBrainz/Spotify) sans rien changer au reste,
et c'est ce point précis qui est instrumenté par les tests de
performance (nombre d'appels, pas exactitude du contenu retourné).

`SeedListResearcher` est l'implémentation du MVP : une petite base de
correspondances connues (couvrant les artistes cités en exemple dans le
cahier des charges) + un repli "Other" à faible confiance pour tout le
reste, sans aucun appel réseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.genres import FALLBACK_GENRE
from app.normalization import normalize_artist_name


@dataclass
class ResearchResult:
    primary_genre: str
    genres: list[str]
    confidence: float
    source: str


class ArtistResearcher(Protocol):
    def research(self, artist_display_name: str) -> ResearchResult: ...


# Jeu de correspondances connues, couvrant les exemples du cahier des
# charges. Clé = forme normalisée (voir normalization.normalize_artist_name).
_SEED: dict[str, ResearchResult] = {
    "niska": ResearchResult("Rap FR", ["Rap FR"], 0.95, "seed"),
    "gazo": ResearchResult("Rap FR", ["Rap FR"], 0.95, "seed"),
    "tiakola": ResearchResult("Rap FR", ["Rap FR"], 0.95, "seed"),
    "hamza": ResearchResult("Rap FR", ["Rap FR"], 0.9, "seed"),
    "booba": ResearchResult("Rap FR", ["Rap FR"], 0.95, "seed"),
    "drake": ResearchResult("Rap US", ["Rap US", "R&B", "Pop"], 0.9, "seed"),
    "bad bunny": ResearchResult("Reggaeton", ["Reggaeton", "Latino"], 0.95, "seed"),
    "karol g": ResearchResult("Reggaeton", ["Reggaeton", "Latino"], 0.95, "seed"),
    "j balvin": ResearchResult("Reggaeton", ["Reggaeton", "Latino"], 0.9, "seed"),
    "skream": ResearchResult("Dubstep", ["Dubstep"], 0.9, "seed"),
    "dimitri vegas like mike": ResearchResult("EDM", ["EDM", "House"], 0.85, "seed"),
    "w w": ResearchResult("EDM", ["EDM"], 0.85, "seed"),
    "charlotte de witte": ResearchResult("Techno", ["Techno"], 0.9, "seed"),
    "amelie lens": ResearchResult("Techno", ["Techno"], 0.9, "seed"),
}


class SeedListResearcher:
    """Implémentation MVP de ArtistResearcher : correspondances connues
    codées en dur + repli "Other" à faible confiance. Aucun appel réseau."""

    def __init__(self, extra_seed: dict[str, ResearchResult] | None = None):
        self._seed = {**_SEED, **(extra_seed or {})}

    def research(self, artist_display_name: str) -> ResearchResult:
        cle = normalize_artist_name(artist_display_name)
        if cle in self._seed:
            return self._seed[cle]
        return ResearchResult(FALLBACK_GENRE, [FALLBACK_GENRE], 0.2, "heuristic_fallback")


class CountingResearcher:
    """Enveloppe un ArtistResearcher pour compter les appels réels — utilisé
    par les tests de performance (voir test_pipeline_batch_lookup.py)."""

    def __init__(self, inner: ArtistResearcher):
        self._inner = inner
        self.call_count = 0
        self.researched_artists: list[str] = []

    def research(self, artist_display_name: str) -> ResearchResult:
        self.call_count += 1
        self.researched_artists.append(artist_display_name)
        return self._inner.research(artist_display_name)
