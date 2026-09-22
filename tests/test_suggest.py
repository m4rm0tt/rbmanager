from __future__ import annotations

from pathlib import Path

import pytest

from rbmanager.etape0 import ErreurConnexion
from rbmanager.pdb_format import TableType
from rbmanager.suggest import suggerer_playlists_classic
from tests.pdb_builder import construire_fichier_pdb, ligne_genre, ligne_playlist_entry, ligne_playlist_tree, ligne_track


@pytest.fixture()
def base_avec_metadonnees(tmp_path: Path) -> Path:
    tables = {
        TableType.GENRES: [ligne_genre(1, "Speed Garage"), ligne_genre(2, "Techno")],
        TableType.TRACKS: [
            # Morceaux déjà dans la playlist "Speed Garage Sets" (genre 1, ~130 BPM).
            ligne_track(100, "Track A", "sg_track_a.mp3", genre_id=1, tempo_bpm=130),
            ligne_track(101, "Track B", "sg_track_b.mp3", genre_id=1, tempo_bpm=132),
            ligne_track(102, "Track C", "sg_track_c.mp3", genre_id=1, tempo_bpm=129),
            # Morceau déjà dans "Techno Hard" (genre 2, ~145 BPM).
            ligne_track(200, "Techno Track", "techno_banger.mp3", genre_id=2, tempo_bpm=145),
            # Nouveau morceau à trier : même genre et BPM proche de la playlist Speed Garage.
            ligne_track(999, "Nouveau Morceau", "speed_garage_new_track.mp3", genre_id=1, tempo_bpm=131),
            # Morceau totalement hors norme (aucun genre connu, BPM très différent).
            ligne_track(888, "Morceau Orphelin", "ambient_drone.mp3", genre_id=0, tempo_bpm=70),
        ],
        TableType.PLAYLIST_TREE: [
            ligne_playlist_tree(10, "Speed Garage Sets"),
            ligne_playlist_tree(20, "Techno Hard"),
        ],
        TableType.PLAYLIST_ENTRIES: [
            ligne_playlist_entry(0, 100, 10),
            ligne_playlist_entry(1, 101, 10),
            ligne_playlist_entry(2, 102, 10),
            ligne_playlist_entry(0, 200, 20),
        ],
    }
    return construire_fichier_pdb(tmp_path, tables)


def test_suggere_la_bonne_playlist_par_genre_et_bpm(base_avec_metadonnees: Path) -> None:
    suggestions, nom_suggere = suggerer_playlists_classic(base_avec_metadonnees, "999")
    assert suggestions, "aucune suggestion renvoyée alors qu'une correspondance évidente existe"
    assert suggestions[0].nom == "Speed Garage Sets"
    assert suggestions[0].score > 0
    assert any("genre" in r for r in suggestions[0].raisons)


def test_playlist_non_correspondante_pas_suggeree(base_avec_metadonnees: Path) -> None:
    suggestions, _ = suggerer_playlists_classic(base_avec_metadonnees, "999")
    noms = [s.nom for s in suggestions]
    assert "Techno Hard" not in noms


def test_morceau_sans_correspondance_suggere_un_nom(base_avec_metadonnees: Path) -> None:
    # Genre 0 = inconnu, donc pas de suggestion de playlist ni de nom (aucun genre à proposer).
    suggestions, nom_suggere = suggerer_playlists_classic(base_avec_metadonnees, "888")
    assert suggestions == []
    assert nom_suggere is None


def test_morceau_introuvable_leve_erreur(base_avec_metadonnees: Path) -> None:
    with pytest.raises(ErreurConnexion, match="introuvable"):
        suggerer_playlists_classic(base_avec_metadonnees, "123456")


def test_suggestion_par_nom_de_fichier_seul(tmp_path: Path) -> None:
    tables = {
        TableType.GENRES: [],
        TableType.TRACKS: [
            ligne_track(1, "Old", "hard_techno_classic.mp3"),
            ligne_track(2, "New", "hard_techno_new_banger.mp3"),
        ],
        TableType.PLAYLIST_TREE: [ligne_playlist_tree(5, "Hard Techno")],
        TableType.PLAYLIST_ENTRIES: [ligne_playlist_entry(0, 1, 5)],
    }
    chemin = construire_fichier_pdb(tmp_path, tables)
    suggestions, _ = suggerer_playlists_classic(chemin, "2")
    assert suggestions
    assert suggestions[0].nom == "Hard Techno"
    assert any("nom du fichier" in r for r in suggestions[0].raisons)
