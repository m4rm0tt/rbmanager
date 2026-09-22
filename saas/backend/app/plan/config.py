"""Configuration de classification éditable par l'utilisateur / le chat
(voir PROJECT_CONTEXT.md §11, §13, §23)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.genres import DEFAULT_GENRES
from app.normalization import normalize_artist_name


@dataclass
class GenreConfig:
    genres: list[str] = field(default_factory=lambda: list(DEFAULT_GENRES))
    # Redirection au niveau du GENRE : ex. {"baile funk": "Latino"} pour
    # "Mets le baile funk dans Latino." Appliqué au genre calculé d'un
    # morceau avant le regroupement en playlists.
    genre_redirects: dict[str, str] = field(default_factory=dict)
    # Overrides au niveau ARTISTE, valables seulement pour CETTE
    # bibliothèque (choix "Only this library" du §23) — ne touchent pas
    # la base de classification partagée.
    artist_overrides: dict[str, str] = field(default_factory=dict)  # normalized_artist_name -> genre

    def add_genre(self, name: str) -> None:
        if name not in self.genres:
            self.genres.append(name)

    def redirect_genre(self, source_genre: str, target_genre: str) -> None:
        self.genre_redirects[source_genre.strip().lower()] = target_genre
        self.add_genre(target_genre)

    def override_artist(self, artist_name: str, genre: str) -> None:
        self.artist_overrides[normalize_artist_name(artist_name)] = genre
        self.add_genre(genre)

    def resolve_genre(self, primary_artist: str, computed_genre: str) -> str:
        """Applique, dans l'ordre : override par artiste (le plus spécifique),
        puis redirection de genre, puis le genre calculé tel quel."""
        override = self.artist_overrides.get(normalize_artist_name(primary_artist))
        if override:
            return override
        return self.genre_redirects.get(computed_genre.strip().lower(), computed_genre)
