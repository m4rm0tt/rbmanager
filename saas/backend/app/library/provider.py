"""
LibraryProvider — abstraction entre le service d'organisation et
l'implémentation concrète de manipulation de la bibliothèque DJ (voir
ARCHITECTURE.md §2 et PROJECT_CONTEXT.md §15).

Le reste du produit (pipeline de classification, planificateur, routes
API) ne dépend que de cette interface, jamais de rbmanager directement.
`RbManagerAdapter` (rbmanager_adapter.py) est l'implémentation MVP ; une
future implémentation pourrait parler à un Local Agent, ou à un autre
format de bibliothèque DJ, sans changer le reste du système.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrackData:
    track_id: str
    title: str
    raw_artist_field: str
    filename: str = ""
    genre_id: str = ""


@dataclass
class PlaylistNode:
    id: str
    name: str
    is_folder: bool
    nb_tracks: int
    children: list["PlaylistNode"] = field(default_factory=list)


class LibraryProvider(ABC):
    """Interface que toute source de bibliothèque DJ doit implémenter."""

    @abstractmethod
    def list_tracks(self) -> list[TrackData]:
        """Renvoie tous les morceaux de la bibliothèque avec leur artiste brut."""

    @abstractmethod
    def list_playlists(self) -> list[PlaylistNode]:
        """Renvoie l'arbre des playlists existantes."""

    @abstractmethod
    def find_playlist_by_name(self, name: str, parent_id: str | None = None) -> PlaylistNode | None:
        """Cherche une playlist par nom (insensible à la casse), pour éviter les doublons à l'apply."""

    @abstractmethod
    def create_playlist(self, name: str, parent_id: str | None = None, is_folder: bool = False) -> str:
        """Crée une playlist (ou un dossier) et renvoie son id. N'écrit pas encore sur disque (voir `save`)."""

    @abstractmethod
    def add_track(self, playlist_id: str, track_id: str) -> None:
        """Ajoute un morceau à une playlist (no-op silencieux si déjà présent — idempotent)."""

    @abstractmethod
    def backup(self) -> Path:
        """Crée une sauvegarde horodatée AVANT toute série d'écritures."""

    @abstractmethod
    def save(self) -> None:
        """Persiste sur disque toutes les modifications faites depuis l'ouverture."""
