"""
Tests des opérations d'écriture sur le format historique export.pdb.

Pour l'instant, seules les opérations "bascule de bit de présence" sont
implémentées (supprimer une playlist, retirer un morceau) : elles ne
déplacent ni ne réorganisent jamais les octets de données, ce qui les
rend beaucoup plus sûres que l'ajout de nouvelles lignes (pas encore
implémenté). Ces tests vérifient que les modifications survivent bien à
un cycle sauvegarde-sur-disque puis relecture.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rbmanager.pdb_format import PdbFile, PdbFormatError

LEN_PAGE = 4096


def _sql_short(s: str) -> bytes:
    data = s.encode("ascii")
    return bytes([2 * len(data) + 3]) + data


def _build_playlist_tree_and_entries(tmp_path: Path, playlists: list[dict], entries: list[tuple[int, int, int]]) -> Path:
    """playlists: [{id, parent_id, is_folder, name}], entries: [(entry_index, track_id, playlist_id)]."""
    buf = bytearray(LEN_PAGE * 3)
    struct.pack_into("<7I", buf, 0, 0, LEN_PAGE, 2, 0, 0, 1, 0)
    struct.pack_into("<4I", buf, 0x1C, 7, 0, 1, 1)
    struct.pack_into("<4I", buf, 0x2C, 8, 0, 2, 2)

    # Page 1 : playlist_tree
    ps = LEN_PAGE * 1
    heap_offset = 0
    offsets = []
    for p in playlists:
        offsets.append(heap_offset)
        addr = ps + 0x28 + heap_offset
        struct.pack_into("<5I", buf, addr, p["parent_id"], 0, 0, p["id"], p.get("is_folder", 0))
        name_bytes = _sql_short(p["name"])
        buf[addr + 0x14 : addr + 0x14 + len(name_bytes)] = name_bytes
        heap_offset += 0x14 + len(name_bytes)
    n = len(playlists)
    rc = n | (n << 13)
    buf[ps + 0x18 : ps + 0x1B] = rc.to_bytes(3, "little")
    struct.pack_into("<6I", buf, ps, 0, 1, 7, 1, 1, 0)
    buf[ps + 0x1B] = 0x24
    struct.pack_into("<HH", buf, ps + 0x1C, 0, heap_offset)
    struct.pack_into("<HHHH", buf, ps + 0x20, 0, 0, 0, 0)
    ge = ps + LEN_PAGE
    for k, ofs in enumerate(offsets):
        struct.pack_into("<H", buf, ge - 6 - 2 * k, ofs)
    struct.pack_into("<H", buf, ge - 4, (1 << n) - 1 if n else 0)
    struct.pack_into("<H", buf, ge - 2, 0)

    # Page 2 : playlist_entries
    ps2 = LEN_PAGE * 2
    for i, (idx, tid, plid) in enumerate(entries):
        struct.pack_into("<3I", buf, ps2 + 0x28 + i * 12, idx, tid, plid)
    m = len(entries)
    rc2 = m | (m << 13)
    buf[ps2 + 0x18 : ps2 + 0x1B] = rc2.to_bytes(3, "little")
    struct.pack_into("<6I", buf, ps2, 0, 2, 8, 2, 1, 0)
    buf[ps2 + 0x1B] = 0x24
    struct.pack_into("<HH", buf, ps2 + 0x1C, 0, m * 12)
    struct.pack_into("<HHHH", buf, ps2 + 0x20, 0, 0, 0, 0)
    ge2 = ps2 + LEN_PAGE
    for k in range(m):
        struct.pack_into("<H", buf, ge2 - 6 - 2 * k, k * 12)
    struct.pack_into("<H", buf, ge2 - 4, (1 << m) - 1 if m else 0)
    struct.pack_into("<H", buf, ge2 - 2, 0)

    path = tmp_path / "export.pdb"
    path.write_bytes(bytes(buf))
    return path


@pytest.fixture()
def base_avec_entries(tmp_path: Path) -> Path:
    return _build_playlist_tree_and_entries(
        tmp_path,
        playlists=[
            dict(id=1, parent_id=0, is_folder=1, name="Genres"),
            dict(id=10, parent_id=1, name="Ma Playlist"),
        ],
        entries=[(0, 111, 10), (1, 222, 10), (2, 333, 10)],
    )


def test_retirer_morceau_persiste_apres_sauvegarde(base_avec_entries: Path) -> None:
    db = PdbFile(base_avec_entries)
    assert db.retirer_morceau("10", "222") is True
    db.enregistrer()

    relu = PdbFile(base_avec_entries)
    track_ids = {e.track_id for e in relu.playlist_entry_rows()}
    assert track_ids == {"111", "333"}


def test_retirer_morceau_absent_renvoie_false(base_avec_entries: Path) -> None:
    db = PdbFile(base_avec_entries)
    assert db.retirer_morceau("10", "999") is False
    # Rien ne doit avoir changé.
    assert {e.track_id for e in db.playlist_entry_rows()} == {"111", "222", "333"}


def test_supprimer_playlist_cascade_les_morceaux(base_avec_entries: Path) -> None:
    db = PdbFile(base_avec_entries)
    nb = db.supprimer_playlist("10")
    assert nb == 3
    db.enregistrer()

    relu = PdbFile(base_avec_entries)
    assert relu.playlist_entry_rows() == []
    assert [p.id for p in relu.playlist_tree_rows()] == ["1"]  # seul le dossier "Genres" reste


def test_supprimer_dossier_refuse(base_avec_entries: Path) -> None:
    db = PdbFile(base_avec_entries)
    with pytest.raises(PdbFormatError, match="dossiers"):
        db.supprimer_playlist("1")


def test_supprimer_playlist_inexistante_leve_erreur(base_avec_entries: Path) -> None:
    db = PdbFile(base_avec_entries)
    with pytest.raises(PdbFormatError, match="introuvable"):
        db.supprimer_playlist("999")


def test_num_rows_valid_decremente_correctement(base_avec_entries: Path) -> None:
    from rbmanager.pdb_format import _parse_page_header

    db = PdbFile(base_avec_entries)
    page_start = LEN_PAGE * 2  # page playlist_entries
    avant = _parse_page_header(bytes(db._buf), page_start)
    assert avant["num_rows_valid"] == 3
    assert avant["num_row_offsets"] == 3  # ne doit jamais bouger lors d'une suppression logique

    db.retirer_morceau("10", "222")
    apres = _parse_page_header(bytes(db._buf), page_start)
    assert apres["num_rows_valid"] == 2
    assert apres["num_row_offsets"] == 3
