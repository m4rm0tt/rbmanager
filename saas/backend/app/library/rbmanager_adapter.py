"""
RbManagerAdapter — implémentation de LibraryProvider au-dessus de
rbmanager (voir ARCHITECTURE.md §1-2). N'utilise QUE l'API publique de
`rbmanager.pdb_format.PdbFile` et les utilitaires `backup`/`journal` du
dépôt : aucune réimplémentation de la lecture/écriture du format
binaire ici.

Ne fonctionne que sur le format DeviceSQL classique (`detecter_format ==
"classic"`) : c'est le seul que rbmanager sait écrire de toute façon
(voir README.md du dépôt) — cohérent avec la limitation déjà documentée.

Une seule sauvegarde par "session" d'écritures (voir `backup()`),
volontairement différent du comportement de la CLI `rbmanager` qui
sauvegarde avant CHAQUE commande individuelle : appliquer un plan
d'organisation peut faire des centaines d'écritures (une par morceau
déplacé), et sauvegarder l'intégralité d'`export.pdb` (plusieurs
centaines de Ko à plusieurs Mo) à chacune serait à la fois inutile
(la sauvegarde d'avant-plan suffit pour un undo) et lent.
"""

from __future__ import annotations

from pathlib import Path

from rbmanager.backup import sauvegarder
from rbmanager.etape0 import detecter_format
from rbmanager.journal import consigner
from rbmanager.pdb_format import PdbFile, PdbFormatError

from app.library.provider import LibraryProvider, PlaylistNode, TrackData


class UnsupportedLibraryFormatError(Exception):
    """La bibliothèque n'est pas au format DeviceSQL classique (seul supporté en écriture)."""


class RbManagerAdapter(LibraryProvider):
    def __init__(self, export_pdb_path: str | Path):
        self.export_pdb_path = Path(export_pdb_path)
        if detecter_format(self.export_pdb_path) != "classic":
            raise UnsupportedLibraryFormatError(
                "Cette bibliothèque est au format SQLCipher (Device Library Plus) : "
                "l'écriture n'est pour l'instant supportée que sur le format DeviceSQL "
                "classique (CDJ/XDJ, dont la XDJ-RX3) — voir README.md de rbmanager."
            )
        self._pdb = PdbFile(self.export_pdb_path)
        self._backup_path: Path | None = None

    # -- lecture ----------------------------------------------------------

    def list_tracks(self) -> list[TrackData]:
        infos = self._pdb.track_info()
        artist_names = self._pdb.artist_names()
        return [
            TrackData(
                track_id=tid,
                title=info.title,
                raw_artist_field=artist_names.get(info.artist_id, "") if info.artist_id != "0" else "",
                filename=info.filename,
                genre_id=info.genre_id,
            )
            for tid, info in infos.items()
        ]

    def list_playlists(self) -> list[PlaylistNode]:
        tree_rows = self._pdb.playlist_tree_rows()
        entries = self._pdb.playlist_entry_rows()

        nb_par_playlist: dict[str, int] = {}
        for e in entries:
            nb_par_playlist[e.playlist_id] = nb_par_playlist.get(e.playlist_id, 0) + 1

        ids_connus = {row.id for row in tree_rows}
        noeuds = {
            row.id: PlaylistNode(
                id=row.id,
                name=row.name or "(sans nom)",
                is_folder=row.is_folder,
                nb_tracks=0 if row.is_folder else nb_par_playlist.get(row.id, 0),
            )
            for row in tree_rows
        }

        racine: list[PlaylistNode] = []
        for row in tree_rows:
            noeud = noeuds[row.id]
            if row.parent_id in ids_connus and row.parent_id != row.id:
                noeuds[row.parent_id].children.append(noeud)
            else:
                racine.append(noeud)
        return racine

    def find_playlist_by_name(self, name: str, parent_id: str | None = None) -> PlaylistNode | None:
        def _aplatir(nodes: list[PlaylistNode]):
            for n in nodes:
                yield n
                yield from _aplatir(n.children)

        cible = name.strip().lower()
        for node in _aplatir(self.list_playlists()):
            if node.name.strip().lower() == cible:
                return node
        return None

    # -- écriture -----------------------------------------------------------

    def create_playlist(self, name: str, parent_id: str | None = None, is_folder: bool = False) -> str:
        try:
            return self._pdb.creer_playlist(name, parent_id=parent_id or "0", is_folder=is_folder)
        except PdbFormatError as exc:
            raise UnsupportedLibraryFormatError(str(exc)) from exc

    def add_track(self, playlist_id: str, track_id: str) -> None:
        try:
            self._pdb.ajouter_morceau(playlist_id, track_id)
        except PdbFormatError as exc:
            if "déjà" in str(exc):
                return  # idempotent : un morceau déjà présent n'est pas une erreur pour l'apply d'un plan.
            raise

    def backup(self) -> Path:
        """Sauvegarde AVANT toute écriture, une seule fois par instance
        (voir la note du module) : les appels suivants renvoient le même chemin."""
        if self._backup_path is None:
            self._backup_path = sauvegarder(self.export_pdb_path)
        return self._backup_path

    def save(self) -> None:
        self._pdb.enregistrer()
        consigner(
            self.export_pdb_path,
            "organize-library",
            f"backup={self._backup_path}" if self._backup_path else "(aucune sauvegarde préalable — lecture seule ?)",
            succes=True,
        )

    def restore_backup(self, backup_path: str | Path) -> None:
        """Undo : recopie une sauvegarde par-dessus le fichier courant (voir plan/apply.py)."""
        import shutil

        shutil.copy2(backup_path, self.export_pdb_path)
        self._pdb = PdbFile(self.export_pdb_path)  # recharge l'état restauré en mémoire
