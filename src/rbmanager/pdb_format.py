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


@dataclass
class RowLocation:
    """Repère une ligne à la fois par son contenu (row_addr) et par l'entrée d'index
    qui la référence (page_start + presence_offset + bit_index), pour permettre de la
    marquer supprimée sans avoir à retrouver ces informations une seconde fois."""

    page_start: int
    presence_addr: int
    bit_index: int
    row_addr: int


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


def _iter_row_slots(buf: bytes, page_start: int, len_page: int, num_row_offsets: int) -> list[RowLocation]:
    """Renvoie une RowLocation pour chaque entrée d'index allouée de la page (présente ou non)."""
    if num_row_offsets == 0:
        return []
    num_groups = (num_row_offsets - 1) // ROW_GROUP_MAX_ROWS + 1
    results: list[RowLocation] = []
    for g in range(num_groups):
        group_end = page_start + len_page - ROW_GROUP_SIZE * g
        presence_addr = group_end - 4
        for k in range(ROW_GROUP_MAX_ROWS):
            ofs_addr = group_end - 6 - 2 * k
            (row_offset,) = struct.unpack_from("<H", buf, ofs_addr)
            results.append(
                RowLocation(
                    page_start=page_start,
                    presence_addr=presence_addr,
                    bit_index=k,
                    row_addr=page_start + HEAP_START + row_offset,
                )
            )
    return results


def _is_present(buf: bytes, loc: RowLocation) -> bool:
    (presence_flags,) = struct.unpack_from("<H", buf, loc.presence_addr)
    return bool((presence_flags >> loc.bit_index) & 1)


def _set_presence(buf: bytearray, loc: RowLocation, present: bool) -> None:
    """Bascule le bit de présence d'une ligne. N'écrit ni ne déplace jamais les octets de la
    ligne elle-même : c'est l'opération d'écriture la plus sûre de ce format (pas de
    réorganisation du tas, pas de risque de chevauchement)."""
    (flags,) = struct.unpack_from("<H", buf, loc.presence_addr)
    if present:
        flags |= 1 << loc.bit_index
    else:
        flags &= ~(1 << loc.bit_index) & 0xFFFF
    struct.pack_into("<H", buf, loc.presence_addr, flags)


def _adjust_num_rows_valid(buf: bytearray, page_start: int, delta: int) -> None:
    """Met à jour le compteur num_rows_valid de l'en-tête de page (num_row_offsets inchangé)."""
    raw = int.from_bytes(buf[page_start + 0x18 : page_start + 0x1B], "little")
    num_row_offsets = raw & 0x1FFF
    num_rows_valid = (raw >> 13) & 0x7FF
    num_rows_valid += delta
    if not 0 <= num_rows_valid <= 0x7FF:
        raise PdbFormatError(
            f"Calcul num_rows_valid invalide à la page {page_start:#x} (delta={delta})."
        )
    new_raw = (num_row_offsets & 0x1FFF) | ((num_rows_valid & 0x7FF) << 13)
    buf[page_start + 0x18 : page_start + 0x1B] = new_raw.to_bytes(3, "little")


def _mark_page_contains_deleted(buf: bytearray, page_start: int) -> None:
    buf[page_start + 0x1B] |= 0x10  # Bit D (deleted), voir doc du format.


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


def _iter_table_row_locations(buf: bytes, header: FileHeader, table: TablePointer, include_deleted: bool = False):
    """Génère une RowLocation pour chaque ligne d'une table (présente, ou aussi supprimée si demandé)."""
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
            for loc in _iter_row_slots(buf, page_start, header.len_page, page["num_row_offsets"]):
                if include_deleted or _is_present(buf, loc):
                    yield loc

        if page_index == table.last_page:
            break
        page_index = page["next_page"]


def _iter_table_rows(buf: bytes, header: FileHeader, table: TablePointer):
    """Génère l'adresse absolue de chaque ligne PRÉSENTE d'une table (pour la lecture)."""
    for loc in _iter_table_row_locations(buf, header, table):
        yield loc.row_addr


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
    """Représentation d'un fichier export.pdb (format historique DeviceSQL).

    Le buffer est chargé entièrement en mémoire sous forme de `bytearray`
    modifiable. Les méthodes d'écriture ne modifient que des bits de
    présence déjà alloués (aucune réorganisation du tas pour l'instant) :
    voir `supprimer_playlist` et `retirer_morceau`. Rien n'est jamais
    écrit sur le disque avant l'appel explicite à `enregistrer()`.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._buf = bytearray(self.path.read_bytes())
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

    def supprimer_playlist(self, playlist_id: str) -> int:
        """Marque une playlist (non-dossier) et tous ses morceaux comme supprimés.

        Renvoie le nombre de morceaux retirés avec elle. La suppression de
        dossiers n'est volontairement pas prise en charge : elle demande
        une logique récursive (enfants, playlists imbriquées) qui n'a pas
        encore été conçue ni testée.
        """
        tree_table = self._table(TableType.PLAYLIST_TREE)
        if tree_table is None:
            raise PdbFormatError("Aucune table playlist_tree dans ce fichier.")

        cible: tuple[RowLocation, PlaylistTreeRow] | None = None
        for loc in _iter_table_row_locations(self._buf, self.header, tree_table):
            row = _parse_playlist_tree_row(self._buf, loc.row_addr)
            if row.id == playlist_id:
                cible = (loc, row)
                break
        if cible is None:
            raise PdbFormatError(f"Playlist introuvable (id={playlist_id}).")
        loc, row = cible
        if row.is_folder:
            raise PdbFormatError(
                "La suppression de dossiers n'est pas encore prise en charge dans rbmanager "
                "(seules les playlists simples peuvent être supprimées pour l'instant)."
            )

        _set_presence(self._buf, loc, False)
        _adjust_num_rows_valid(self._buf, loc.page_start, -1)
        _mark_page_contains_deleted(self._buf, loc.page_start)

        nb_retires = 0
        entries_table = self._table(TableType.PLAYLIST_ENTRIES)
        if entries_table is not None:
            for eloc in _iter_table_row_locations(self._buf, self.header, entries_table):
                entry = _parse_playlist_entry_row(self._buf, eloc.row_addr)
                if entry.playlist_id == playlist_id:
                    _set_presence(self._buf, eloc, False)
                    _adjust_num_rows_valid(self._buf, eloc.page_start, -1)
                    _mark_page_contains_deleted(self._buf, eloc.page_start)
                    nb_retires += 1
        return nb_retires

    def retirer_morceau(self, playlist_id: str, track_id: str) -> bool:
        """Retire un morceau d'une playlist. Renvoie False si l'association n'existait pas."""
        table = self._table(TableType.PLAYLIST_ENTRIES)
        if table is None:
            raise PdbFormatError("Aucune table playlist_entries dans ce fichier.")
        for loc in _iter_table_row_locations(self._buf, self.header, table):
            entry = _parse_playlist_entry_row(self._buf, loc.row_addr)
            if entry.playlist_id == playlist_id and entry.track_id == track_id:
                _set_presence(self._buf, loc, False)
                _adjust_num_rows_valid(self._buf, loc.page_start, -1)
                _mark_page_contains_deleted(self._buf, loc.page_start)
                return True
        return False

    def enregistrer(self, chemin: str | Path | None = None) -> None:
        """Écrit le contenu (éventuellement modifié) sur le disque.

        Ne fait aucune sauvegarde elle-même : voir `rbmanager.backup` pour
        la copie de sécurité qui doit systématiquement précéder cet appel.
        """
        cible = Path(chemin) if chemin else self.path
        cible.write_bytes(bytes(self._buf))
