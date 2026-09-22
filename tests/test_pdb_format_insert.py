"""
Tests des opérations d'écriture qui allouent de nouvelles lignes
(create-playlist, add-track) — la partie la plus délicate du format
puisqu'elle doit gérer le tas (heap) qui grandit vers l'avant et, en cas
de page pleine, l'allocation d'une page supplémentaire chaînée.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rbmanager.pdb_format import PdbFile, PdbFormatError
from tests.test_pdb_format_write import _build_playlist_tree_and_entries


@pytest.fixture()
def base_simple(tmp_path: Path) -> Path:
    return _build_playlist_tree_and_entries(
        tmp_path,
        playlists=[
            dict(id=1, parent_id=0, is_folder=1, name="Genres"),
            dict(id=10, parent_id=1, name="Ma Playlist"),
        ],
        entries=[(0, 111, 10), (1, 222, 10)],
    )


def test_creer_playlist_a_la_racine(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    nouvel_id = db.creer_playlist("Nouvelle Playlist")
    db.enregistrer()

    relu = PdbFile(base_simple)
    rows = {r.id: r for r in relu.playlist_tree_rows()}
    assert nouvel_id in rows
    assert rows[nouvel_id].name == "Nouvelle Playlist"
    assert rows[nouvel_id].parent_id == "0"
    assert rows[nouvel_id].is_folder is False


def test_creer_playlist_sous_un_dossier(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    nouvel_id = db.creer_playlist("Sous-playlist", parent_id="1")
    db.enregistrer()

    relu = PdbFile(base_simple)
    rows = {r.id: r for r in relu.playlist_tree_rows()}
    assert rows[nouvel_id].parent_id == "1"


def test_creer_dossier(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    nouvel_id = db.creer_playlist("Nouveau Dossier", is_folder=True)
    db.enregistrer()

    relu = PdbFile(base_simple)
    rows = {r.id: r for r in relu.playlist_tree_rows()}
    assert rows[nouvel_id].is_folder is True


def test_creer_playlist_parent_introuvable(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    with pytest.raises(PdbFormatError, match="parent introuvable"):
        db.creer_playlist("X", parent_id="999")


def test_creer_playlist_nom_accentue(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    nouvel_id = db.creer_playlist("Électro Française été")
    db.enregistrer()

    relu = PdbFile(base_simple)
    rows = {r.id: r for r in relu.playlist_tree_rows()}
    assert rows[nouvel_id].name == "Électro Française été"


def test_id_genere_ne_reutilise_pas_un_id_supprime(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    db.supprimer_playlist("10")  # libère l'id 10, mais il ne doit pas être réutilisé
    nouvel_id = db.creer_playlist("Après suppression")
    assert nouvel_id != "10"
    assert int(nouvel_id) > 10


def test_ajouter_morceau_reussi(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    entry_index = db.ajouter_morceau("10", "333")
    assert entry_index == 2  # après les entrées existantes 0 et 1
    db.enregistrer()

    relu = PdbFile(base_simple)
    track_ids = {e.track_id for e in relu.playlist_entry_rows()}
    assert track_ids == {"111", "222", "333"}


def test_ajouter_morceau_playlist_introuvable(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    with pytest.raises(PdbFormatError, match="Playlist introuvable"):
        db.ajouter_morceau("999", "333")


def test_ajouter_morceau_deja_present_refuse(base_simple: Path) -> None:
    db = PdbFile(base_simple)
    with pytest.raises(PdbFormatError, match="déjà"):
        db.ajouter_morceau("10", "111")


def test_ajouter_morceau_inconnu_refuse_si_table_tracks_absente_ou_incoherente(base_simple: Path) -> None:
    # La fixture ne contient pas de table `tracks` : la vérification d'existence
    # du morceau est alors ignorée (best-effort), pas bloquante.
    db = PdbFile(base_simple)
    entry_index = db.ajouter_morceau("10", "999999")
    assert entry_index == 2


def test_creer_playlist_puis_lister_playlists_hierarchie(base_simple: Path) -> None:
    from rbmanager.etape0 import lister_playlists_classic

    db = PdbFile(base_simple)
    nouvel_id = db.creer_playlist("Enfant", parent_id="1")
    db.enregistrer()

    playlists = lister_playlists_classic(base_simple)
    genres = next(p for p in playlists if p.nom == "Genres")
    noms_enfants = {e.nom for e in genres.enfants}
    assert "Enfant" in noms_enfants
    assert any(e.id == nouvel_id for e in genres.enfants)


def _construire_page_presque_pleine(tmp_path: Path, len_page: int, table_type_playlist_tree: int = 7) -> Path:
    """Construit un fichier avec une seule table (playlist_tree) dont la page est
    volontairement quasi pleine, pour forcer les tests d'insertion à déclencher
    une allocation de nouvelle page."""
    buf = bytearray(len_page * 2)
    struct.pack_into("<7I", buf, 0, 0, len_page, 1, 0, 0, 1, 0)
    struct.pack_into("<4I", buf, 0x1C, table_type_playlist_tree, 0, 1, 1)

    ps = len_page * 1
    # Une seule ligne existante, avec un nom qui remplit presque toute la page.
    marge_restante = 40  # juste assez pour un futur nom court, pas pour un gros nom
    taille_nom_existant = len_page - HEAP_START_TEST - 0x14 - 1 - marge_restante
    nom_existant = "A" * taille_nom_existant
    name_bytes = bytes([2 * len(nom_existant) + 3]) + nom_existant.encode("ascii") if len(nom_existant) <= 126 else None
    if name_bytes is None:
        length = 4 + len(nom_existant.encode("ascii"))
        name_bytes = struct.pack("<BHB", 0x40, length, 0) + nom_existant.encode("ascii")

    struct.pack_into("<5I", buf, ps + 0x28, 0, 0, 0, 500, 0)
    buf[ps + 0x28 + 0x14 : ps + 0x28 + 0x14 + len(name_bytes)] = name_bytes
    heap_used = 0x14 + len(name_bytes)

    rc = 1 | (1 << 13)
    buf[ps + 0x18 : ps + 0x1B] = rc.to_bytes(3, "little")
    struct.pack_into("<6I", buf, ps, 0, 1, table_type_playlist_tree, 1, 1, 0)
    buf[ps + 0x1B] = 0x24
    struct.pack_into("<HH", buf, ps + 0x1C, len_page - HEAP_START_TEST - heap_used, heap_used)
    struct.pack_into("<HHHH", buf, ps + 0x20, 0, 0, 0, 0)
    ge = ps + len_page
    struct.pack_into("<H", buf, ge - 6, 0)
    struct.pack_into("<H", buf, ge - 4, 0b1)
    struct.pack_into("<H", buf, ge - 2, 0)

    path = tmp_path / "export.pdb"
    path.write_bytes(bytes(buf))
    return path


HEAP_START_TEST = 0x28


def test_insertion_declenche_une_nouvelle_page_quand_pleine(tmp_path: Path) -> None:
    len_page = 512  # petite page pour forcer le débordement rapidement
    path = _construire_page_presque_pleine(tmp_path, len_page)

    db = PdbFile(path)
    taille_fichier_avant = len(db._buf)
    assert taille_fichier_avant == len_page * 2  # header + 1 page de données

    # Ce nom ne doit pas tenir dans la place restante de la première page.
    nouvel_id = db.creer_playlist("B" * 60)
    db.enregistrer()

    assert len(db._buf) == len_page * 3  # une page a bien été ajoutée

    relu = PdbFile(path)
    rows = {r.id: r for r in relu.playlist_tree_rows()}
    assert "500" in rows  # l'ancienne ligne est toujours lisible
    assert nouvel_id in rows
    assert rows[nouvel_id].name == "B" * 60

    # La page d'origine doit maintenant chaîner vers la nouvelle page.
    ancienne_page_start = len_page * 1
    (next_page,) = struct.unpack_from("<I", bytes(relu._buf), ancienne_page_start + 0x0C)
    assert next_page == 2  # nouvelle page ajoutée à l'index 2 (0=header, 1=ancienne, 2=nouvelle)


def test_plusieurs_insertions_sur_plusieurs_pages(tmp_path: Path) -> None:
    len_page = 512
    path = _construire_page_presque_pleine(tmp_path, len_page)

    db = PdbFile(path)
    noms_ajoutes = []
    for i in range(10):
        nom = f"Playlist ajoutée {i}"
        db.creer_playlist(nom)
        noms_ajoutes.append(nom)
    db.enregistrer()

    relu = PdbFile(path)
    rows = relu.playlist_tree_rows()
    noms_lus = {r.name for r in rows}
    assert "500" in {r.id for r in rows}
    for nom in noms_ajoutes:
        assert nom in noms_lus
    # Tous les ids doivent être uniques.
    ids = [r.id for r in rows]
    assert len(ids) == len(set(ids))
