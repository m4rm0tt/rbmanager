"""
Espace de travail serveur pour une bibliothèque uploadée (voir
ARCHITECTURE.md §2 : le MVP cloud reçoit un `export.pdb` uploadé, le
traite côté serveur, et le fichier modifié est retéléchargé par
l'utilisateur — pas d'accès direct à une clé USB depuis le cloud).

La structure de dossiers reproduit volontairement celle d'une vraie clé
USB (`<racine>/PIONEER/rekordbox/export.pdb`) : `rbmanager.backup` et
`rbmanager.journal` en dépendent (ils remontent 3 niveaux depuis
`export.pdb` pour trouver `backups/`/`logs/`), donc les réutiliser tels
quels sans les modifier suffit à obtenir le même comportement de
sauvegarde/journalisation qu'un usage direct de rbmanager sur une clé.
"""

from __future__ import annotations

import uuid
from pathlib import Path


def library_export_pdb_path(workspace_root: Path, library_id: str) -> Path:
    return workspace_root / library_id / "PIONEER" / "rekordbox" / "export.pdb"


def create_library_workspace(workspace_root: Path, uploaded_bytes: bytes) -> str:
    """Écrit les octets uploadés dans un nouvel espace de travail et renvoie son id."""
    library_id = uuid.uuid4().hex
    chemin = library_export_pdb_path(workspace_root, library_id)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(uploaded_bytes)
    return library_id
