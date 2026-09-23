"""
Tests de l'extraction des artistes (table `artists` + champ `artist_id`
des pistes) — base de la classification par artiste (voir le futur
service d'organisation automatique de bibliothèque).
"""

from __future__ import annotations

import struct
from pathlib import Path

from rbmanager.pdb_format import PdbFile, TableType
from tests.pdb_builder import construire_fichier_pdb, ligne_artist, ligne_track


def test_artist_names_lit_les_noms_courts(tmp_path: Path) -> None:
    tables = {
        TableType.ARTISTS: [ligne_artist(1, "Niska"), ligne_artist(2, "Gazo")],
        TableType.TRACKS: [],
    }
    chemin = construire_fichier_pdb(tmp_path, tables)
    db = PdbFile(chemin)
    assert db.artist_names() == {"1": "Niska", "2": "Gazo"}


def test_track_info_expose_artist_id(tmp_path: Path) -> None:
    tables = {
        TableType.ARTISTS: [ligne_artist(1, "Niska")],
        TableType.TRACKS: [
            ligne_track(100, "Reseaux", "reseaux.mp3", artist_id=1),
            ligne_track(101, "Sans artiste", "inconnu.mp3"),
        ],
    }
    chemin = construire_fichier_pdb(tmp_path, tables)
    db = PdbFile(chemin)
    infos = db.track_info()
    assert infos["100"].artist_id == "1"
    assert infos["101"].artist_id == "0"


def test_croisement_track_artist_donne_le_nom(tmp_path: Path) -> None:
    """Vérifie le chemin complet Track -> artist_id -> table artists -> nom,
    tel qu'utilisé par le pipeline de classification par artiste."""
    tables = {
        TableType.ARTISTS: [ligne_artist(1, "Niska"), ligne_artist(2, "Drake")],
        TableType.TRACKS: [
            ligne_track(100, "Reseaux", artist_id=1),
            ligne_track(101, "Medicament", artist_id=1),
            ligne_track(200, "Hotline Bling", artist_id=2),
        ],
    }
    chemin = construire_fichier_pdb(tmp_path, tables)
    db = PdbFile(chemin)
    artistes = db.artist_names()
    infos = db.track_info()

    noms = {tid: artistes.get(info.artist_id, "") for tid, info in infos.items()}
    assert noms == {"100": "Niska", "101": "Niska", "200": "Drake"}


def test_artist_names_table_absente_renvoie_dict_vide(tmp_path: Path) -> None:
    tables = {TableType.TRACKS: [ligne_track(1, "Solo")]}
    chemin = construire_fichier_pdb(tmp_path, tables)
    db = PdbFile(chemin)
    assert db.artist_names() == {}


def test_artist_row_offset_long_far_offset(tmp_path: Path) -> None:
    """Cas rare : nom d'artiste trop loin dans le tas pour un offset 1 octet
    (subtype & 0x04), ex. après une longue chaîne de padding devant lui."""
    tables = {
        TableType.ARTISTS: [
            # Padding : artiste "bouche-trou" avec un nom volontairement long
            # pour repousser le nom du second artiste au-delà de 0xFF octets
            # depuis le début de SA PROPRE ligne (on construit la ligne à la main).
        ],
        TableType.TRACKS: [],
    }
    # Construction manuelle d'une ligne artist avec subtype=0x64 (far offset).
    fixe = bytearray(12)
    struct.pack_into("<H", fixe, 0x00, 0x64)  # subtype avec bit "long name"
    struct.pack_into("<I", fixe, 0x04, 42)
    fixe[0x08] = 0x03
    nom = "Collectif Tres Long Nom D'Artiste"
    data = nom.encode("ascii")
    name_offset = len(fixe)
    struct.pack_into("<H", fixe, 0x0A, name_offset)
    row = bytes(fixe) + bytes([2 * len(data) + 3]) + data

    tables[TableType.ARTISTS] = [row]
    chemin = construire_fichier_pdb(tmp_path, tables)
    db = PdbFile(chemin)
    assert db.artist_names() == {"42": nom}
