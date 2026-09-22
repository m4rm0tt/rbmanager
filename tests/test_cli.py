"""Tests de la CLI unifiée (rbmanager.cli) : commandes non-interactives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rbmanager import cli
from rbmanager.pdb_format import TableType
from tests.pdb_builder import construire_fichier_pdb, ligne_genre, ligne_playlist_entry, ligne_playlist_tree, ligne_track
from tests.test_pdb_format_write import _build_playlist_tree_and_entries


@pytest.fixture()
def cle_usb(tmp_path: Path) -> Path:
    export_pdb = _build_playlist_tree_and_entries(
        tmp_path,
        playlists=[
            dict(id=1, parent_id=0, is_folder=1, name="Genres"),
            dict(id=10, parent_id=1, name="Ma Playlist"),
        ],
        entries=[(0, 111, 10), (1, 222, 10), (2, 333, 10)],
    )
    # export_pdb est déjà sous tmp_path/export.pdb ; on le déplace à l'emplacement attendu.
    racine = tmp_path / "cle"
    cible = racine / "PIONEER" / "rekordbox" / "export.pdb"
    cible.parent.mkdir(parents=True)
    export_pdb.rename(cible)
    return racine


def test_list_playlists_json(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["list-playlists", "--usb", str(cle_usb), "--format", "json"])
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is True
    assert sortie["format_detecte"] == "classic"
    noms = {p["nom"] for p in sortie["playlists"]}
    assert noms == {"Genres"}
    assert sortie["playlists"][0]["enfants"][0]["nom"] == "Ma Playlist"


def test_show_playlist_json(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["show-playlist", "--usb", str(cle_usb), "--playlist-id", "10", "--format", "json"])
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["nb_morceaux"] == 3
    assert [m["id"] for m in sortie["morceaux"]] == ["111", "222", "333"]


def test_show_playlist_introuvable(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["show-playlist", "--usb", str(cle_usb), "--playlist-id", "999", "--format", "json"])
    assert code == 6
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is False


def test_remove_track_puis_relecture(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["remove-track", "--usb", str(cle_usb), "--playlist-id", "10", "--track-id", "222", "--format", "json"]
    )
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is True
    assert (cle_usb / "backups").exists()

    code2 = cli.main(["show-playlist", "--usb", str(cle_usb), "--playlist-id", "10", "--format", "json"])
    sortie2 = json.loads(capsys.readouterr().out)
    assert code2 == 0
    assert [m["id"] for m in sortie2["morceaux"]] == ["111", "333"]


def test_delete_playlist_dossier_refuse(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["delete-playlist", "--usb", str(cle_usb), "--playlist-id", "1", "--format", "json"])
    assert code == 7
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is False


def test_delete_playlist_reussie(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["delete-playlist", "--usb", str(cle_usb), "--playlist-id", "10", "--format", "json"])
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["nb_morceaux_retires"] == 3

    code2 = cli.main(["list-playlists", "--usb", str(cle_usb), "--format", "json"])
    sortie2 = json.loads(capsys.readouterr().out)
    assert code2 == 0
    # Seul le dossier "Genres" reste, désormais sans enfants.
    assert sortie2["playlists"][0]["enfants"] == []


def test_create_playlist_puis_lecture(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["create-playlist", "--usb", str(cle_usb), "--name", "Toute Nouvelle", "--format", "json"])
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is True
    nouvel_id = sortie["playlist_id"]

    code2 = cli.main(["list-playlists", "--usb", str(cle_usb), "--format", "json"])
    sortie2 = json.loads(capsys.readouterr().out)
    noms_racine = {p["nom"]: p["id"] for p in sortie2["playlists"]}
    assert noms_racine.get("Toute Nouvelle") == nouvel_id


def test_create_playlist_parent_introuvable(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["create-playlist", "--usb", str(cle_usb), "--name", "X", "--parent-id", "999", "--format", "json"]
    )
    assert code == 6
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is False


def test_add_track_puis_show_playlist(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["add-track", "--usb", str(cle_usb), "--playlist-id", "10", "--track-id", "444", "--format", "json"]
    )
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["entry_index"] == 3

    code2 = cli.main(["show-playlist", "--usb", str(cle_usb), "--playlist-id", "10", "--format", "json"])
    sortie2 = json.loads(capsys.readouterr().out)
    assert [m["id"] for m in sortie2["morceaux"]] == ["111", "222", "333", "444"]


def test_add_track_deja_present(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["add-track", "--usb", str(cle_usb), "--playlist-id", "10", "--track-id", "111", "--format", "json"]
    )
    assert code == 9
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is False


@pytest.fixture()
def cle_usb_avec_metadonnees(tmp_path: Path) -> Path:
    tables = {
        TableType.GENRES: [ligne_genre(1, "Speed Garage")],
        TableType.TRACKS: [
            ligne_track(100, "Track A", "sg_a.mp3", genre_id=1, tempo_bpm=130),
            ligne_track(101, "Track B", "sg_b.mp3", genre_id=1, tempo_bpm=131),
            ligne_track(999, "Nouveau", "sg_nouveau.mp3", genre_id=1, tempo_bpm=129),
        ],
        TableType.PLAYLIST_TREE: [ligne_playlist_tree(10, "Speed Garage Sets")],
        TableType.PLAYLIST_ENTRIES: [ligne_playlist_entry(0, 100, 10), ligne_playlist_entry(1, 101, 10)],
    }
    export_pdb = construire_fichier_pdb(tmp_path, tables)
    racine = tmp_path / "cle-meta"
    cible = racine / "PIONEER" / "rekordbox" / "export.pdb"
    cible.parent.mkdir(parents=True)
    export_pdb.rename(cible)
    return racine


def test_suggest_playlist_json(cle_usb_avec_metadonnees: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["suggest-playlist", "--usb", str(cle_usb_avec_metadonnees), "--track-id", "999", "--format", "json"]
    )
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["succes"] is True
    assert sortie["suggestions"]
    assert sortie["suggestions"][0]["nom"] == "Speed Garage Sets"


def test_journal_consigne_les_ecritures(cle_usb: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["remove-track", "--usb", str(cle_usb), "--playlist-id", "10", "--track-id", "222", "--format", "json"])
    capsys.readouterr()
    journal = cle_usb / "logs" / "rbmanager.log"
    assert journal.exists()
    contenu = journal.read_text(encoding="utf-8")
    assert "remove-track" in contenu
    assert "OK" in contenu
