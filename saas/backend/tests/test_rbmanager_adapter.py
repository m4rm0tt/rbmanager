"""
Tests de RbManagerAdapter — construit des fichiers export.pdb
synthétiques avec le même utilitaire que les tests de rbmanager lui-même
(tests/pdb_builder.py, à la racine du dépôt) pour ne pas dupliquer la
logique de construction du format binaire.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pdb_builder import construire_fichier_pdb, ligne_artist, ligne_playlist_entry, ligne_playlist_tree, ligne_track
from rbmanager.pdb_format import TableType

from app.library.provider import TrackData
from app.library.rbmanager_adapter import RbManagerAdapter
from app.library.workspace import create_library_workspace, library_export_pdb_path


@pytest.fixture()
def bibliotheque(tmp_path: Path) -> Path:
    tables = {
        TableType.ARTISTS: [ligne_artist(1, "Niska"), ligne_artist(2, "Gazo")],
        TableType.TRACKS: [
            ligne_track(100, "Reseaux", "reseaux.mp3", artist_id=1),
            ligne_track(101, "Bandana", "bandana.mp3", artist_id=2),
            ligne_track(102, "Sans artiste", artist_id=0),
        ],
        TableType.PLAYLIST_TREE: [ligne_playlist_tree(10, "Import")],
        TableType.PLAYLIST_ENTRIES: [
            ligne_playlist_entry(0, 100, 10),
            ligne_playlist_entry(1, 101, 10),
            ligne_playlist_entry(2, 102, 10),
        ],
    }
    return construire_fichier_pdb(tmp_path, tables)


def test_list_tracks_resout_le_nom_d_artiste(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    tracks = {t.track_id: t for t in adapter.list_tracks()}
    assert tracks["100"] == TrackData(track_id="100", title="Reseaux", raw_artist_field="Niska", filename="reseaux.mp3", genre_id="0")
    assert tracks["101"].raw_artist_field == "Gazo"
    assert tracks["102"].raw_artist_field == ""  # artist_id == 0 -> pas d'artiste


def test_list_playlists(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    playlists = adapter.list_playlists()
    assert len(playlists) == 1
    assert playlists[0].name == "Import"
    assert playlists[0].nb_tracks == 3


def test_find_playlist_by_name_insensible_a_la_casse(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    trouve = adapter.find_playlist_by_name("IMPORT")
    assert trouve is not None
    assert trouve.id == "10"
    assert adapter.find_playlist_by_name("n'existe pas") is None


def test_create_playlist_et_add_track_puis_save(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    backup_path = adapter.backup()
    assert backup_path.exists()

    playlist_id = adapter.create_playlist("Rap FR")
    adapter.add_track(playlist_id, "100")
    adapter.add_track(playlist_id, "101")
    adapter.save()

    # Relecture depuis le disque pour vérifier la persistance réelle.
    relu = RbManagerAdapter(bibliotheque)
    nouvelle_playlist = relu.find_playlist_by_name("Rap FR")
    assert nouvelle_playlist is not None
    assert nouvelle_playlist.nb_tracks == 2


def test_add_track_idempotent(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    playlist_id = adapter.create_playlist("Rap FR")
    adapter.add_track(playlist_id, "100")
    adapter.add_track(playlist_id, "100")  # ne doit pas lever d'erreur
    adapter.save()

    relu = RbManagerAdapter(bibliotheque)
    assert relu.find_playlist_by_name("Rap FR").nb_tracks == 1


def test_backup_une_seule_fois_par_instance(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    p1 = adapter.backup()
    p2 = adapter.backup()
    assert p1 == p2


def test_undo_restaure_la_sauvegarde(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    backup_path = adapter.backup()

    playlist_id = adapter.create_playlist("Playlist Temporaire")
    adapter.add_track(playlist_id, "100")
    adapter.save()
    assert RbManagerAdapter(bibliotheque).find_playlist_by_name("Playlist Temporaire") is not None

    adapter.restore_backup(backup_path)
    assert RbManagerAdapter(bibliotheque).find_playlist_by_name("Playlist Temporaire") is None


def test_workspace_reproduit_la_structure_de_cle_usb(tmp_path: Path):
    workspace_root = tmp_path / "workspaces"
    library_id = create_library_workspace(workspace_root, bibliotheque_bytes(tmp_path))
    chemin = library_export_pdb_path(workspace_root, library_id)
    assert chemin.exists()
    assert chemin.parent.name == "rekordbox"
    assert chemin.parent.parent.name == "PIONEER"

    adapter = RbManagerAdapter(chemin)
    adapter.backup()
    assert (chemin.parent.parent.parent / "backups").exists()


def bibliotheque_bytes(tmp_path: Path) -> bytes:
    dossier = tmp_path / "src_lib"
    dossier.mkdir()
    tables = {TableType.TRACKS: [ligne_track(1, "Solo")]}
    chemin = construire_fichier_pdb(dossier, tables)
    return chemin.read_bytes()
