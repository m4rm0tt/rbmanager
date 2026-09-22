"""
Tests du parseur du format historique export.pdb (DeviceSQL, non chiffré,
utilisé par les CDJ/XDJ classiques dont la XDJ-RX3).

Comme il n'existe pas de bibliothèque de référence à comparer (pyrekordbox
ne supporte pas ce format), ces tests construisent des fichiers .pdb
synthétiques octet par octet en suivant strictement la spécification
communautaire, pour valider indépendamment chaque partie délicate du
format : calcul des offsets de ligne, groupes de lignes multiples,
lignes supprimées, chaînage de pages avec page d'index, et les
différents encodages de chaînes DeviceSQL.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from rbmanager.pdb_format import PdbFile, _parse_playlist_entry_row, _parse_track_title, _read_device_sql_string

LEN_PAGE = 4096


def _device_sql_short_ascii(s: str) -> bytes:
    data = s.encode("ascii")
    length_and_kind = 2 * len(data) + 3
    return bytes([length_and_kind]) + data


def _write_playlist_tree_page(buf, page_index, next_page, rows, len_page=LEN_PAGE, deleted_indices=frozenset()):
    """Écrit une page de données playlist_tree contenant `rows` (dicts) à page_index."""
    page_start = len_page * page_index
    heap_offset = 0
    offsets = []
    for r in rows:
        offsets.append(heap_offset)
        addr = page_start + 0x28 + heap_offset
        struct.pack_into("<5I", buf, addr, r["parent_id"], 0, r["sort_order"], r["id"], r.get("is_folder", 0))
        name_bytes = _device_sql_short_ascii(r["name"])
        buf[addr + 0x14 : addr + 0x14 + len(name_bytes)] = name_bytes
        heap_offset += 0x14 + len(name_bytes)

    num_row_offsets = len(rows)
    num_rows_valid = num_row_offsets - len(deleted_indices)
    row_counts_raw = num_row_offsets | (num_rows_valid << 13)
    buf[page_start + 0x18 : page_start + 0x1B] = row_counts_raw.to_bytes(3, "little")

    struct.pack_into("<6I", buf, page_start, 0, page_index, 7, next_page, 1, 0)
    buf[page_start + 0x1B] = 0x24 if not deleted_indices else 0x34
    struct.pack_into("<HH", buf, page_start + 0x1C, 0, heap_offset)
    struct.pack_into("<HHHH", buf, page_start + 0x20, 0, 0, 0, 0)

    num_groups = (num_row_offsets - 1) // 16 + 1 if num_row_offsets else 0
    for g in range(num_groups):
        group_end = page_start + len_page - 36 * g
        presence = 0
        for local_k in range(16):
            global_i = g * 16 + local_k
            ofs_addr = group_end - 6 - 2 * local_k
            ofs_value = offsets[global_i] if global_i < len(offsets) else 0
            struct.pack_into("<H", buf, ofs_addr, ofs_value)
            if global_i < len(offsets) and global_i not in deleted_indices:
                presence |= 1 << local_k
        struct.pack_into("<H", buf, group_end - 4, presence)
        struct.pack_into("<H", buf, group_end - 2, 0)


def _write_index_page(buf, page_index, next_page, len_page=LEN_PAGE):
    page_start = len_page * page_index
    struct.pack_into("<6I", buf, page_start, 0, page_index, 7, next_page, 1, 0)
    buf[page_start + 0x1B] = 0x64


def _write_file_header(buf, len_page, table_type, first_page, last_page):
    struct.pack_into("<7I", buf, 0, 0, len_page, 1, 0, 0, 1, 0)
    struct.pack_into("<4I", buf, 0x1C, table_type, 0, first_page, last_page)


@pytest.fixture()
def simple_playlist_tree(tmp_path: Path) -> Path:
    buf = bytearray(LEN_PAGE * 2)
    _write_file_header(buf, LEN_PAGE, table_type=7, first_page=1, last_page=1)
    rows = [
        dict(parent_id=0, sort_order=1, id=1, is_folder=1, name="Genres"),
        dict(parent_id=1, sort_order=1, id=2, is_folder=0, name="Speed Garage"),
        dict(parent_id=1, sort_order=2, id=3, is_folder=0, name="UK Garage"),
        dict(parent_id=0, sort_order=2, id=4, is_folder=0, name="Hard Techno"),
    ]
    _write_playlist_tree_page(buf, 1, next_page=0, rows=rows)
    path = tmp_path / "export.pdb"
    path.write_bytes(bytes(buf))
    return path


def test_playlist_tree_hierarchie_simple(simple_playlist_tree: Path) -> None:
    db = PdbFile(simple_playlist_tree)
    rows = db.playlist_tree_rows()
    assert [r.name for r in rows] == ["Genres", "Speed Garage", "UK Garage", "Hard Techno"]
    genres = next(r for r in rows if r.name == "Genres")
    assert genres.is_folder is True
    speed_garage = next(r for r in rows if r.name == "Speed Garage")
    assert speed_garage.parent_id == genres.id
    assert speed_garage.is_folder is False


def test_plusieurs_groupes_et_lignes_supprimees(tmp_path: Path) -> None:
    buf = bytearray(LEN_PAGE * 2)
    _write_file_header(buf, LEN_PAGE, table_type=7, first_page=1, last_page=1)
    rows = [dict(parent_id=0, sort_order=i, id=100 + i, name=f"Playlist{i:02d}") for i in range(18)]
    _write_playlist_tree_page(buf, 1, next_page=0, rows=rows, deleted_indices={5})
    path = tmp_path / "export.pdb"
    path.write_bytes(bytes(buf))

    db = PdbFile(path)
    names = [r.name for r in db.playlist_tree_rows()]
    assert len(names) == 17
    assert "Playlist05" not in names
    assert names == [f"Playlist{i:02d}" for i in range(18) if i != 5]


def test_chainage_de_pages_avec_page_index(tmp_path: Path) -> None:
    len_page = 1024
    buf = bytearray(len_page * 4)
    _write_file_header(buf, len_page, table_type=7, first_page=1, last_page=3)
    _write_index_page(buf, 1, next_page=2, len_page=len_page)
    _write_playlist_tree_page(buf, 2, next_page=3, rows=[dict(parent_id=0, sort_order=0, id=200, name="Alpha")], len_page=len_page)
    _write_playlist_tree_page(buf, 3, next_page=0, rows=[dict(parent_id=0, sort_order=1, id=201, name="Beta")], len_page=len_page)
    path = tmp_path / "export.pdb"
    path.write_bytes(bytes(buf))

    db = PdbFile(path)
    assert [r.name for r in db.playlist_tree_rows()] == ["Alpha", "Beta"]


def test_playlist_entry_row() -> None:
    buf = bytearray(20)
    struct.pack_into("<3I", buf, 0, 7, 42, 3)
    entry = _parse_playlist_entry_row(bytes(buf), 0)
    assert entry.entry_index == 7
    assert entry.track_id == "42"
    assert entry.playlist_id == "3"


def test_track_title() -> None:
    buf = bytearray(300)
    addr = 10
    struct.pack_into("<I", buf, addr + 0x48, 555)
    ofs = [0] * 21
    title_rel_offset = 0x64 + 21 * 2
    ofs[17] = title_rel_offset
    struct.pack_into("<21H", buf, addr + 0x64, *ofs)
    name_bytes = _device_sql_short_ascii("Ma Piste Test")
    buf[addr + title_rel_offset : addr + title_rel_offset + len(name_bytes)] = name_bytes

    track_id, title = _parse_track_title(bytes(buf), addr)
    assert track_id == "555"
    assert title == "Ma Piste Test"


@pytest.mark.parametrize(
    "kind,text",
    [
        ("short_ascii", "Test Court"),
        ("long_ascii", "A" * 130),
        ("long_utf16le", "Ünïcödé Title"),
    ],
)
def test_device_sql_string_encodages(kind: str, text: str) -> None:
    buf = bytearray(400)
    if kind == "short_ascii":
        data = _device_sql_short_ascii(text)
        buf[: len(data)] = data
    elif kind == "long_ascii":
        data = text.encode("ascii")
        length = 4 + len(data)
        struct.pack_into("<BHB", buf, 0, 0x40, length, 0)
        buf[4 : 4 + len(data)] = data
    else:
        data = text.encode("utf-16-le")
        length = 4 + len(data)
        struct.pack_into("<BHB", buf, 0, 0x90, length, 0)
        buf[4 : 4 + len(data)] = data

    assert _read_device_sql_string(bytes(buf), 0) == text
