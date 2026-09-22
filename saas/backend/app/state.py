"""
État applicatif partagé (MVP mono-process — voir ARCHITECTURE.md §2).

- `classification_repo` : LA base de connaissance partagée entre TOUTES
  les bibliothèques et TOUS les utilisateurs (un seul fichier SQLite),
  cœur du produit (PROJECT_CONTEXT.md §6-7-27).
- `history_repo` : historique des organisations (§20).
- `_adapters` / `_configs` : état en mémoire PAR bibliothèque uploadée
  (l'adapter garde le fichier `export.pdb` ouvert et modifiable tant que
  le process tourne ; la config de genres est éditée par le chat).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.classification.db_repo import ArtistClassificationRepo
from app.classification.research import SeedListResearcher
from app.library.rbmanager_adapter import RbManagerAdapter
from app.library.workspace import library_export_pdb_path
from app.plan.config import GenreConfig
from app.plan.history import HistoryRepo

DATA_DIR = Path(os.environ.get("DJ_ORGANIZER_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_ROOT = DATA_DIR / "workspaces"
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

classification_repo = ArtistClassificationRepo(DATA_DIR / "artist_classifications.db")
history_repo = HistoryRepo(DATA_DIR / "history.db")
researcher = SeedListResearcher()

_adapters: dict[str, RbManagerAdapter] = {}
_configs: dict[str, GenreConfig] = {}


class LibraryNotFoundError(Exception):
    pass


def get_adapter(library_id: str) -> RbManagerAdapter:
    if library_id not in _adapters:
        chemin = library_export_pdb_path(WORKSPACE_ROOT, library_id)
        if not chemin.exists():
            raise LibraryNotFoundError(library_id)
        _adapters[library_id] = RbManagerAdapter(chemin)
    return _adapters[library_id]


def get_config(library_id: str) -> GenreConfig:
    return _configs.setdefault(library_id, GenreConfig())


def set_config(library_id: str, config: GenreConfig) -> None:
    _configs[library_id] = config


def reload_adapter(library_id: str) -> RbManagerAdapter:
    """Force la relecture depuis le disque (après un undo par exemple)."""
    chemin = library_export_pdb_path(WORKSPACE_ROOT, library_id)
    _adapters[library_id] = RbManagerAdapter(chemin)
    return _adapters[library_id]
