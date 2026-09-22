"""
Constructeur générique de fichiers export.pdb (format historique DeviceSQL)
synthétiques pour les tests, avec plusieurs tables (genres, tracks,
playlist_tree, playlist_entries...). Complète les constructeurs plus
spécifiques de test_pdb_format.py / test_pdb_format_write.py, utile quand
un test a besoin de plusieurs tables en même temps (ex: suggest.py qui
croise tracks + genres + playlist_entries + playlist_tree).
"""

from __future__ import annotations

import struct
from pathlib import Path

HEAP_START = 0x28


def sql_short(s: str) -> bytes:
    data = s.encode("ascii")
    return bytes([2 * len(data) + 3]) + data


def ligne_genre(id_: int, nom: str) -> bytes:
    return struct.pack("<I", id_) + sql_short(nom)


def ligne_key(id_: int, nom: str) -> bytes:
    return struct.pack("<II", id_, id_) + sql_short(nom)


def ligne_artist(id_: int, nom: str) -> bytes:
    """Construit une ligne `artists` (subtype=0x60, nom toujours en offset court `ofs_name_near`,
    suffisant pour des noms d'artiste réalistes — voir _parse_artist_row pour le cas long)."""
    fixe = bytearray(10)  # 0x00 subtype, 0x02 index_shift, 0x04 id, 0x08 unknown, 0x09 ofs_name_near
    struct.pack_into("<H", fixe, 0x00, 0x60)
    struct.pack_into("<I", fixe, 0x04, id_)
    fixe[0x08] = 0x03
    fixe[0x09] = len(fixe)
    return bytes(fixe) + sql_short(nom)


def ligne_playlist_tree(id_: int, nom: str, parent_id: int = 0, is_folder: int = 0, sort_order: int = 0) -> bytes:
    return struct.pack("<5I", parent_id, 0, sort_order, id_, is_folder) + sql_short(nom)


def ligne_playlist_entry(entry_index: int, track_id: int, playlist_id: int) -> bytes:
    return struct.pack("<3I", entry_index, track_id, playlist_id)


def ligne_track(
    id_: int,
    titre: str,
    filename: str = "",
    genre_id: int = 0,
    key_id: int = 0,
    artist_id: int = 0,
    tempo_bpm: float = 0.0,
) -> bytes:
    """Construit une ligne `tracks` minimale (uniquement les champs utilisés par rbmanager)."""
    fixe = bytearray(0x88)  # 0x5E (champs fixes) + 21*2 (tableau d'offsets de strings) = 136
    struct.pack_into("<H", fixe, 0x00, 0x24)  # subtype
    struct.pack_into("<I", fixe, 0x20, key_id)
    struct.pack_into("<I", fixe, 0x38, round(tempo_bpm * 100))
    struct.pack_into("<I", fixe, 0x3C, genre_id)
    struct.pack_into("<I", fixe, 0x44, artist_id)
    struct.pack_into("<I", fixe, 0x48, id_)

    titre_bytes = sql_short(titre) if titre else b""
    filename_bytes = sql_short(filename) if filename else b""

    ofs = [0] * 21
    pos = len(fixe)
    if titre_bytes:
        ofs[17] = pos
        pos += len(titre_bytes)
    if filename_bytes:
        ofs[19] = pos
        pos += len(filename_bytes)
    struct.pack_into("<21H", fixe, 0x5E, *ofs)

    return bytes(fixe) + titre_bytes + filename_bytes


def construire_fichier_pdb(tmp_path: Path, tables_rows: dict[int, list[bytes]], len_page: int = 8192) -> Path:
    """Construit un export.pdb avec une page de données par table (suffisant pour les
    tests : chaque table de test reste petite). `tables_rows` associe un type de table
    (voir `TableType`) à la liste des lignes déjà encodées (voir les `ligne_*` ci-dessus)."""
    num_tables = len(tables_rows)
    num_pages = 1 + num_tables
    buf = bytearray(len_page * num_pages)
    struct.pack_into("<7I", buf, 0, 0, len_page, num_tables, 0, 0, 1, 0)

    for i, (table_type, rows) in enumerate(tables_rows.items()):
        page_idx = i + 1
        struct.pack_into("<4I", buf, 0x1C + 16 * i, table_type, 0, page_idx, page_idx)

        ps = len_page * page_idx
        heap_offset = 0
        offsets = []
        for row_bytes in rows:
            offsets.append(heap_offset)
            addr = ps + HEAP_START + heap_offset
            buf[addr : addr + len(row_bytes)] = row_bytes
            heap_offset += len(row_bytes)

        n = len(rows)
        rc = n | (n << 13)
        buf[ps + 0x18 : ps + 0x1B] = rc.to_bytes(3, "little")
        struct.pack_into("<6I", buf, ps, 0, page_idx, table_type, page_idx, 1, 0)
        buf[ps + 0x1B] = 0x24
        struct.pack_into("<HH", buf, ps + 0x1C, len_page - HEAP_START - heap_offset, heap_offset)
        struct.pack_into("<HHHH", buf, ps + 0x20, 0, 0, 0, 0)

        if n:
            ge = ps + len_page
            for k, ofs in enumerate(offsets):
                struct.pack_into("<H", buf, ge - 6 - 2 * k, ofs)
            struct.pack_into("<H", buf, ge - 4, (1 << n) - 1)
            struct.pack_into("<H", buf, ge - 2, 0)

    chemin = tmp_path / "export.pdb"
    chemin.write_bytes(bytes(buf))
    return chemin
