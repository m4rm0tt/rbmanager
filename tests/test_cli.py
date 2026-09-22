"""Tests de la CLI unifiée (rbmanager.cli) : commandes non-interactives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rbmanager import cli
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
