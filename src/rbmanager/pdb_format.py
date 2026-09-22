"""
Lecteur (et bientôt écrivain) du format binaire historique `export.pdb`
utilisé par Rekordbox pour les clés USB compatibles CDJ/XDJ classiques
(dont la XDJ-RX3) — à ne pas confondre avec `master.db`/"Device Library
Plus" (SQLite chiffré SQLCipher), que la bibliothèque `pyrekordbox` sait
lire mais qui ne concerne PAS ce format.

Ce format n'est pas documenté officiellement par Pioneer : il a été
rétro-ingénié par la communauté (Henry Betts, Fabian Lesniak, et le
projet Deep Symmetry "Crate Digger"). La spécification de référence :
https://github.com/Deep-Symmetry/crate-digger/blob/main/doc/modules/ROOT/pages/exports.adoc
https://github.com/Deep-Symmetry/crate-digger/blob/master/src/main/kaitai/rekordbox_pdb.ksy

Les calculs d'offsets ci-dessous ont été vérifiés par recoupement avec
l'implémentation indépendante `rekordcrate` (Rust, binrw) :
https://github.com/Holzhaus/rekordcrate/blob/main/src/pdb/mod.rs
Ce recoupement a d'ailleurs permis de corriger une ambiguïté du document
Kaitai sur l'ordre des bits du champ `row_counts` (voir `PageHeader`
ci-dessous : c'est bien num_row_offsets qui occupe les bits de poids
FAIBLE, malgré ce que suggérait une première lecture de la doc).

Aucune donnée n'est chiffrée dans ce format : contrairement à master.db,
il n'y a pas de clé à trouver. C'est un format purement binaire à plat.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

PAGE_COMMON_HEADER_SIZE = 0x20  # Champs communs à toutes les pages (page_index, type, ...).
DATA_PAGE_HEADER_SIZE = 0x08  # Champs spécifiques aux pages de données (tran_rc, tran_ri, ...).
HEAP_START = PAGE_COMMON_HEADER_SIZE + DATA_PAGE_HEADER_SIZE  # 0x28 : début du heap dans une page de données.
ROW_GROUP_SIZE = 36  # 16 offsets (2 octets) + row_presence_flags (2) + unknown/transaction (2).
ROW_GROUP_MAX_ROWS = 16
PAGE_FLAG_IS_INDEX = 0x40  # Bit 6 : page d'index (pas de lignes de données) si positionné.


class TableType(IntEnum):
    TRACKS = 0
    GENRES = 1
    ARTISTS = 2
    ALBUMS = 3
    LABELS = 4
    KEYS = 5
    COLORS = 6
    PLAYLIST_TREE = 7
    PLAYLIST_ENTRIES = 8
    HISTORY_PLAYLISTS = 11
    HISTORY_ENTRIES = 12
    ARTWORK = 13
    COLUMNS = 16
    HISTORY = 19


class PdbFormatError(Exception):
    """Le fichier ne respecte pas la structure attendue du format export.pdb."""


@dataclass
class TablePointer:
    type: int
    empty_candidate: int
    first_page: int
    last_page: int


@dataclass
class FileHeader:
    len_page: int
    num_tables: int
    next_unused_page: int
    sequence: int
    tables: list[TablePointer]


@dataclass
class PlaylistTreeRow:
    id: str
    parent_id: str
    sort_order: int
    is_folder: bool
    name: str


@dataclass
class PlaylistEntryRow:
    entry_index: int
    track_id: str
    playlist_id: str


def _read_device_sql_string(buf: bytes, pos: int) -> str:
    """Décode une chaîne DeviceSQL (courte ASCII, longue ASCII, ou longue UTF-16LE)."""
    length_and_kind = buf[pos]
    if length_and_kind & 0x01:
        # Chaîne courte ASCII : le reste des 7 bits = longueur totale / 2 (voir doc).
        length = length_and_kind >> 1
        return buf[pos + 1 : pos + length].decode("ascii", errors="replace")

    # Chaîne longue : lengthAndKind est un jeu de drapeaux (ASCII vs UTF-16LE),
    # suivi d'une longueur 16 bits (en-tête de 4 octets compris) puis d'un padding.
    (length,) = struct.unpack_from("<H", buf, pos + 1)
    data_start = pos + 4
    data_end = pos + length
    if length_and_kind == 0x90:
        return buf[data_start:data_end].decode("utf-16-le", errors="replace")
    return buf[data_start:data_end].decode("ascii", errors="replace")


def _parse_file_header(buf: bytes) -> FileHeader:
    if len(buf) < 0x1C:
        raise PdbFormatError("Fichier trop court pour contenir un en-tête export.pdb valide.")

    zero, len_page, num_tables, next_unused_page, _reserved, sequence, _gap = struct.unpack_from(
        "<7I", buf, 0
    )
    if zero != 0:
        raise PdbFormatError(
            "Les 4 premiers octets ne sont pas nuls : ce fichier n'est pas un export.pdb "
            "classique (peut-être un master.db chiffré, ou un fichier corrompu)."
        )
    if len_page == 0 or len_page > len(buf):
        raise PdbFormatError(f"Taille de page invalide dans l'en-tête ({len_page}).")

    tables = []
    offset = 0x1C
    for _ in range(num_tables):
        table_type, empty_candidate, first_page, last_page = struct.unpack_from("<4I", buf, offset)
        tables.append(TablePointer(table_type, empty_candidate, first_page, last_page))
        offset += 16

    return FileHeader(len_page, num_tables, next_unused_page, sequence, tables)


def _iter_row_offsets(buf: bytes, page_start: int, len_page: int, num_row_offsets: int) -> list[tuple[int, bool]]:
    """Renvoie [(offset_dans_le_heap, present), ...] pour toutes les lignes allouées de la page."""
    if num_row_offsets == 0:
        return []
    num_groups = (num_row_offsets - 1) // ROW_GROUP_MAX_ROWS + 1
    results: list[tuple[int, bool]] = []
    for g in range(num_groups):
        group_end = page_start + len_page - ROW_GROUP_SIZE * g
        group_start = group_end - ROW_GROUP_SIZE
        (presence_flags,) = struct.unpack_from("<H", buf, group_start + 32)
        for k in range(ROW_GROUP_MAX_ROWS):
            ofs_addr = group_end - 6 - 2 * k
            (row_offset,) = struct.unpack_from("<H", buf, ofs_addr)
            present = bool((presence_flags >> k) & 1)
            results.append((row_offset, present))
    return results


def _parse_page_header(buf: bytes, page_start: int) -> dict[str, Any]:
    (
        zero,
        page_index,
        page_type,
        next_page,
        sequence,
        _unknown2,
    ) = struct.unpack_from("<6I", buf, page_start)
    if zero != 0:
        raise PdbFormatError(f"En-tête de page invalide à l'offset {page_start:#x} (page {page_index}).")

    row_counts_raw = int.from_bytes(buf[page_start + 0x18 : page_start + 0x1B], "little")
    num_row_offsets = row_counts_raw & 0x1FFF  # 13 bits de poids faible : lignes jamais désallouées.
    num_rows_valid = (row_counts_raw >> 13) & 0x7FF  # 11 bits de poids fort : lignes valides actuellement.

    page_flags = buf[page_start + 0x1B]

    return {
        "page_index": page_index,
        "type": page_type,
        "next_page": next_page,
        "num_row_offsets": num_row_offsets,
        "num_rows_valid": num_rows_valid,
        "page_flags": page_flags,
        "is_index_page": bool(page_flags & PAGE_FLAG_IS_INDEX),
    }


def _iter_table_rows(buf: bytes, header: FileHeader, table: TablePointer):
    """Génère (adresse_absolue_de_la_ligne,) pour chaque ligne présente d'une table."""
    page_index = table.first_page
    seen_pages = set()
    while True:
        if page_index in seen_pages:
            raise PdbFormatError(f"Boucle détectée dans la liste chaînée de pages (page {page_index}).")
        seen_pages.add(page_index)

        page_start = page_index * header.len_page
        if page_start + header.len_page > len(buf):
            raise PdbFormatError(f"Page {page_index} hors des limites du fichier.")

        page = _parse_page_header(buf, page_start)

        if not page["is_index_page"]:
            for row_offset, present in _iter_row_offsets(buf, page_start, header.len_page, page["num_row_offsets"]):
                if present:
                    yield page_start + HEAP_START + row_offset

        if page_index == table.last_page:
            break
        page_index = page["next_page"]


def _parse_playlist_tree_row(buf: bytes, addr: int) -> PlaylistTreeRow:
    parent_id, _unknown, sort_order, id_, raw_is_folder = struct.unpack_from("<5I", buf, addr)
    name = _read_device_sql_string(buf, addr + 0x14)
    return PlaylistTreeRow(
        id=str(id_),
        parent_id=str(parent_id),
        sort_order=sort_order,
        is_folder=raw_is_folder != 0,
        name=name,
    )


def _parse_playlist_entry_row(buf: bytes, addr: int) -> PlaylistEntryRow:
    entry_index, track_id, playlist_id = struct.unpack_from("<3I", buf, addr)
    return PlaylistEntryRow(entry_index=entry_index, track_id=str(track_id), playlist_id=str(playlist_id))


def _parse_track_title(buf: bytes, addr: int) -> tuple[str, str]:
    """Renvoie (id, titre) d'une ligne de la table tracks (on ignore le reste pour l'instant)."""
    (id_,) = struct.unpack_from("<I", buf, addr + 0x48)
    ofs_strings = struct.unpack_from("<21H", buf, addr + 0x64)
    title_offset = ofs_strings[17]
    title = _read_device_sql_string(buf, addr + title_offset) if title_offset else ""
    return str(id_), title


class PdbFile:
    """Représentation en lecture seule d'un fichier export.pdb (format historique DeviceSQL)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._buf = self.path.read_bytes()
        self.header = _parse_file_header(self._buf)

    def _table(self, table_type: TableType) -> TablePointer | None:
        for t in self.header.tables:
            if t.type == table_type:
                return t
        return None

    def playlist_tree_rows(self) -> list[PlaylistTreeRow]:
        table = self._table(TableType.PLAYLIST_TREE)
        if table is None:
            return []
        return [_parse_playlist_tree_row(self._buf, addr) for addr in _iter_table_rows(self._buf, self.header, table)]

    def playlist_entry_rows(self) -> list[PlaylistEntryRow]:
        table = self._table(TableType.PLAYLIST_ENTRIES)
        if table is None:
            return []
        return [_parse_playlist_entry_row(self._buf, addr) for addr in _iter_table_rows(self._buf, self.header, table)]

    def track_titles(self) -> dict[str, str]:
        """Renvoie {track_id: titre} pour toutes les pistes de la base."""
        table = self._table(TableType.TRACKS)
        if table is None:
            return {}
        titles = {}
        for addr in _iter_table_rows(self._buf, self.header, table):
            track_id, title = _parse_track_title(self._buf, addr)
            titles[track_id] = title
        return titles
