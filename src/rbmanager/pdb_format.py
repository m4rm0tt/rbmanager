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
class TrackInfo:
    id: str
    title: str
    genre_id: str
    key_id: str
    artist_id: str
    tempo_bpm: float
    filename: str


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
    """Renvoie une RowLocation pour chaque entrée d'index réellement allouée de la page
    (présente ou non). S'arrête à `num_row_offsets`, pas à 16 par groupe : les emplacements
    du dernier groupe qui n'ont encore jamais été utilisés ne pointent vers rien de valide
    (ce sont juste des octets à zéro dans un groupe fraîchement créé) et ne doivent donc
    jamais être renvoyés, même en mode `include_deleted` (voir `_iter_table_row_locations`)."""
    if num_row_offsets == 0:
        return []
    num_groups = _num_row_groups(num_row_offsets)
    results: list[RowLocation] = []
    for g in range(num_groups):
        group_end = page_start + len_page - ROW_GROUP_SIZE * g
        presence_addr = group_end - 4
        nb_dans_ce_groupe = min(ROW_GROUP_MAX_ROWS, num_row_offsets - g * ROW_GROUP_MAX_ROWS)
        for k in range(nb_dans_ce_groupe):
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


def _encode_device_sql_string(s: str) -> bytes:
    """Encode une chaîne au format DeviceSQL (inverse de `_read_device_sql_string`).

    Utilise la forme courte ASCII quand c'est possible (<= 126 octets),
    sinon la forme longue ASCII, sinon UTF-16LE (pour les caractères
    accentués : ni ASCII ni la forme courte ne peuvent les représenter).
    """
    try:
        data = s.encode("ascii")
    except UnicodeEncodeError:
        data = s.encode("utf-16-le")
        longueur_totale = len(data) + 4
        if longueur_totale > 0xFFFF:
            raise PdbFormatError("Nom trop long pour le format DeviceSQL.") from None
        return struct.pack("<BHB", 0x90, longueur_totale, 0) + data

    if len(data) <= 126:
        return bytes([2 * len(data) + 3]) + data

    longueur_totale = len(data) + 4
    if longueur_totale > 0xFFFF:
        raise PdbFormatError("Nom trop long pour le format DeviceSQL.")
    return struct.pack("<BHB", 0x40, longueur_totale, 0) + data


def _num_row_groups(num_row_offsets: int) -> int:
    return (num_row_offsets - 1) // ROW_GROUP_MAX_ROWS + 1 if num_row_offsets else 0


def _page_index_boundary(len_page: int, num_row_offsets: int) -> int:
    """Adresse (relative au début de la page) avant laquelle le tas peut s'étendre
    sans empiéter sur la zone d'index des lignes (qui grandit depuis la fin)."""
    return len_page - ROW_GROUP_SIZE * _num_row_groups(num_row_offsets)


def _set_row_counts(buf: bytearray, page_start: int, num_row_offsets: int, num_rows_valid: int) -> None:
    if not (0 <= num_row_offsets <= 0x1FFF and 0 <= num_rows_valid <= 0x7FF):
        raise PdbFormatError(f"Compteurs de lignes hors limites à la page {page_start:#x}.")
    raw = (num_row_offsets & 0x1FFF) | ((num_rows_valid & 0x7FF) << 13)
    buf[page_start + 0x18 : page_start + 0x1B] = raw.to_bytes(3, "little")


def _init_page_bytes(len_page: int, page_index: int, page_type: int, sequence: int) -> bytearray:
    """Construit une page de données neuve et vide (0 ligne), prête à recevoir des insertions."""
    page = bytearray(len_page)
    struct.pack_into("<6I", page, 0, 0, page_index, page_type, page_index, sequence, 0)
    _set_row_counts(page, 0, 0, 0)
    page[0x1B] = 0x24  # Page de données, pas de ligne supprimée.
    struct.pack_into("<HH", page, 0x1C, len_page - HEAP_START, 0)  # free_size, used_size
    struct.pack_into("<HHHH", page, 0x20, 0, 0, 0, 0)
    return page


def _allouer_nouvelle_page(buf: bytearray, header: FileHeader, page_type: int) -> int:
    """Ajoute une page neuve à la fin du fichier et renvoie son index."""
    nouvel_index = len(buf) // header.len_page
    sequence_pour_la_page = header.sequence
    header.sequence += 1  # seq_db est incrémenté après avoir servi à la page (voir doc du format).
    buf.extend(_init_page_bytes(header.len_page, nouvel_index, page_type, sequence_pour_la_page))
    struct.pack_into("<I", buf, 0x0C, nouvel_index + 1)  # next_unused_page : informationnel, tenu à jour par sécurité.
    struct.pack_into("<I", buf, 0x14, header.sequence)
    return nouvel_index


def _mettre_a_jour_pointeur_table(buf: bytearray, header: FileHeader, table_index: int) -> None:
    """Réécrit dans le fichier le pointeur de table (first_page/last_page) après modification en mémoire."""
    table = header.tables[table_index]
    offset = 0x1C + 16 * table_index
    struct.pack_into("<4I", buf, offset, table.type, table.empty_candidate, table.first_page, table.last_page)


def _inserer_ligne(buf: bytearray, header: FileHeader, table_index: int, row_bytes: bytes) -> RowLocation:
    """Ajoute `row_bytes` comme nouvelle ligne à la fin d'une table (allocation en pile,
    jamais de réutilisation des trous laissés par des suppressions — comme Rekordbox
    lui-même, voir la doc du format).

    Alloue une nouvelle page si la dernière page de la table est pleine, ou si elle
    n'est encore qu'une page d'index vide (table qui n'a jamais reçu de ligne).
    """
    table = header.tables[table_index]
    page_index = table.last_page
    page_start = page_index * header.len_page
    page = _parse_page_header(buf, page_start)

    if page["is_index_page"]:
        num_row_offsets = 0
        num_rows_valid = 0
        used_size = 0
    else:
        num_row_offsets = page["num_row_offsets"]
        num_rows_valid = page["num_rows_valid"]
        (used_size,) = struct.unpack_from("<H", buf, page_start + 0x1E)

    nouveau_num_row_offsets = num_row_offsets + 1
    limite = _page_index_boundary(header.len_page, nouveau_num_row_offsets)
    espace_necessaire = HEAP_START + used_size + len(row_bytes)

    if page["is_index_page"] or espace_necessaire > limite:
        # Espace insuffisant (ou pas encore de page de données) : on en crée une nouvelle.
        nouvel_index = _allouer_nouvelle_page(buf, header, table.type)
        ancien_last_page_start = page_start
        struct.pack_into("<I", buf, ancien_last_page_start + 0x0C, nouvel_index)  # next_page de l'ancienne dernière page
        table.last_page = nouvel_index
        _mettre_a_jour_pointeur_table(buf, header, table_index)

        page_index = nouvel_index
        page_start = page_index * header.len_page
        num_row_offsets = 0
        num_rows_valid = 0
        used_size = 0
        nouveau_num_row_offsets = 1
        limite = _page_index_boundary(header.len_page, nouveau_num_row_offsets)

    # Écriture de la ligne dans le tas, à la suite des données déjà présentes.
    row_addr = page_start + HEAP_START + used_size
    buf[row_addr : row_addr + len(row_bytes)] = row_bytes

    group_index = num_row_offsets // ROW_GROUP_MAX_ROWS
    subindex = num_row_offsets % ROW_GROUP_MAX_ROWS
    group_end = page_start + header.len_page - ROW_GROUP_SIZE * group_index
    if subindex == 0:
        # Nouveau groupe : on l'initialise proprement (offsets à zéro, rien de présent).
        buf[group_end - ROW_GROUP_SIZE : group_end] = bytes(ROW_GROUP_SIZE)

    ofs_addr = group_end - 6 - 2 * subindex
    struct.pack_into("<H", buf, ofs_addr, used_size)
    presence_addr = group_end - 4
    (flags,) = struct.unpack_from("<H", buf, presence_addr)
    flags |= 1 << subindex
    struct.pack_into("<H", buf, presence_addr, flags)

    nouveau_used_size = used_size + len(row_bytes)
    nouveau_free_size = limite - (HEAP_START + nouveau_used_size)
    _set_row_counts(buf, page_start, nouveau_num_row_offsets, num_rows_valid + 1)
    struct.pack_into("<HH", buf, page_start + 0x1C, max(nouveau_free_size, 0), nouveau_used_size)

    return RowLocation(page_start=page_start, presence_addr=presence_addr, bit_index=subindex, row_addr=row_addr)


def _generer_nouvel_id(buf: bytes, header: FileHeader, table_type: TableType, lire_id) -> int:
    """Renvoie max(id existants, y compris supprimés) + 1, ou 1 si la table est vide.

    On inclut les lignes supprimées dans le calcul pour ne jamais réutiliser un ID,
    même si la ligne qui le portait a depuis été retirée.
    """
    table = None
    for t in header.tables:
        if t.type == table_type:
            table = t
            break
    if table is None:
        return 1
    max_id = 0
    for loc in _iter_table_row_locations(buf, header, table, include_deleted=True):
        max_id = max(max_id, lire_id(buf, loc.row_addr))
    return max_id + 1


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


# Offset (relatif au début d'une ligne `tracks`) où commence le tableau des 21
# pointeurs de chaînes. La documentation en prose de la spec (exports.adoc)
# affirme que c'est 0x64, mais c'est une erreur : elle oublie que "file_type"
# (2 octets) et le champ mystère valant toujours 3 (2 octets) suivent
# immédiatement `rating`, sans les 6 octets d'écart qu'elle sous-entend. La
# spec Kaitai Struct (rekordbox_pdb.ksy), elle, est cohérente avec ce calcul,
# et 0x5E a été vérifié directement sur une vraie base export.pdb (le champ
# juste avant, à 0x5C, vaut bien 3 comme attendu, et les décalages obtenus à
# partir de 0x5E pointent vers du texte cohérent, alors que 0x64 pointait
# n'importe où dans le tas, avec des résultats qui ressemblaient par hasard à
# du texte).
TRACK_OFS_STRINGS_OFFSET = 0x5E

# Offset (relatif au début d'une ligne `tracks`) du champ artist_id (u4),
# qui référence une ligne de la table `artists`. Vérifié par recoupement
# avec la spec Kaitai communautaire (rekordbox_pdb.ksy) : composer_id
# (+0x0C), artwork_id (+0x1C), key_id (+0x20, déjà vérifié ci-dessus sur
# une vraie base), original_artist_id (+0x24), label_id (+0x28),
# remixer_id (+0x2C), bitrate (+0x30), track_number (+0x34), tempo
# (+0x38, déjà vérifié), genre_id (+0x3C, déjà vérifié), album_id (+0x40),
# artist_id (+0x44), id (+0x48, déjà vérifié) — la cohérence des trois
# offsets déjà validés sur une vraie base (key_id/tempo/genre_id/id) avec
# cette spec confirme la position des champs non encore exploités.
TRACK_ARTIST_ID_OFFSET = 0x44

# Offsets (relatifs au début d'une ligne `artists`) : cf. artist_row dans
# rekordbox_pdb.ksy. subtype (u2, +0x00) vaut normalement 0x60 ; s'il vaut
# 0x64 (bit 0x04 positionné), le nom est trop loin (>0xFF octets) pour
# tenir dans l'offset court `ofs_name_near` (u1, +0x09) et il faut lire
# `ofs_name_far` (u2, +0x0A) à la place — cas rare pour un nom d'artiste,
# mais géré pour rester correct sur des noms atypiques (collectifs, etc.).
ARTIST_ID_OFFSET = 0x04
ARTIST_OFS_NAME_NEAR_OFFSET = 0x09
ARTIST_OFS_NAME_FAR_OFFSET = 0x0A
ARTIST_SUBTYPE_LONG_NAME_BIT = 0x04


def _parse_track_title(buf: bytes, addr: int) -> tuple[str, str]:
    """Renvoie (id, titre) d'une ligne de la table tracks (on ignore le reste pour l'instant)."""
    (id_,) = struct.unpack_from("<I", buf, addr + 0x48)
    ofs_strings = struct.unpack_from("<21H", buf, addr + TRACK_OFS_STRINGS_OFFSET)
    title_offset = ofs_strings[17]
    title = _read_device_sql_string(buf, addr + title_offset) if title_offset else ""
    return str(id_), title


def _parse_track_info(buf: bytes, addr: int) -> TrackInfo:
    """Renvoie les métadonnées d'une piste utiles au tri semi-automatique et à la classification par artiste."""
    (key_id,) = struct.unpack_from("<I", buf, addr + 0x20)
    (artist_id,) = struct.unpack_from("<I", buf, addr + TRACK_ARTIST_ID_OFFSET)
    (tempo,) = struct.unpack_from("<I", buf, addr + 0x38)
    (genre_id,) = struct.unpack_from("<I", buf, addr + 0x3C)
    (id_,) = struct.unpack_from("<I", buf, addr + 0x48)
    ofs_strings = struct.unpack_from("<21H", buf, addr + TRACK_OFS_STRINGS_OFFSET)
    title = _read_device_sql_string(buf, addr + ofs_strings[17]) if ofs_strings[17] else ""
    filename = _read_device_sql_string(buf, addr + ofs_strings[19]) if ofs_strings[19] else ""
    return TrackInfo(
        id=str(id_),
        title=title,
        genre_id=str(genre_id),
        key_id=str(key_id),
        artist_id=str(artist_id),
        tempo_bpm=tempo / 100,
        filename=filename,
    )


def _parse_genre_or_label_row(buf: bytes, addr: int) -> tuple[str, str]:
    (id_,) = struct.unpack_from("<I", buf, addr)
    return str(id_), _read_device_sql_string(buf, addr + 4)


def _parse_key_row(buf: bytes, addr: int) -> tuple[str, str]:
    (id_,) = struct.unpack_from("<I", buf, addr)
    return str(id_), _read_device_sql_string(buf, addr + 8)


def _parse_artist_row(buf: bytes, addr: int) -> tuple[str, str]:
    """Renvoie (id, nom) d'une ligne de la table `artists`.

    Contrairement à `genre`/`label`/`key` (id puis chaîne directement à un
    offset fixe), le nom d'artiste est référencé par un offset variable
    (`ofs_name_near`, ou `ofs_name_far` si le nom est trop loin dans le
    tas pour tenir sur un seul octet) — voir les constantes ARTIST_*
    ci-dessus, dérivées de la spec Kaitai communautaire.
    """
    (subtype,) = struct.unpack_from("<H", buf, addr)
    (id_,) = struct.unpack_from("<I", buf, addr + ARTIST_ID_OFFSET)
    if subtype & ARTIST_SUBTYPE_LONG_NAME_BIT:
        (name_offset,) = struct.unpack_from("<H", buf, addr + ARTIST_OFS_NAME_FAR_OFFSET)
    else:
        name_offset = buf[addr + ARTIST_OFS_NAME_NEAR_OFFSET]
    name = _read_device_sql_string(buf, addr + name_offset) if name_offset else ""
    return str(id_), name


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

    def _table_index(self, table_type: TableType) -> int:
        for i, t in enumerate(self.header.tables):
            if t.type == table_type:
                return i
        raise PdbFormatError(f"Aucune table de type {table_type.name} dans ce fichier.")

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

    def track_info(self) -> dict[str, TrackInfo]:
        """Renvoie {track_id: TrackInfo} avec les métadonnées utiles au tri semi-automatique."""
        table = self._table(TableType.TRACKS)
        if table is None:
            return {}
        infos = (_parse_track_info(self._buf, addr) for addr in _iter_table_rows(self._buf, self.header, table))
        return {info.id: info for info in infos}

    def genre_names(self) -> dict[str, str]:
        table = self._table(TableType.GENRES)
        if table is None:
            return {}
        return dict(_parse_genre_or_label_row(self._buf, addr) for addr in _iter_table_rows(self._buf, self.header, table))

    def key_names(self) -> dict[str, str]:
        table = self._table(TableType.KEYS)
        if table is None:
            return {}
        return dict(_parse_key_row(self._buf, addr) for addr in _iter_table_rows(self._buf, self.header, table))

    def artist_names(self) -> dict[str, str]:
        """Renvoie {artist_id: nom} pour tous les artistes de la base.

        À croiser avec `TrackInfo.artist_id` (voir `track_info`) pour
        obtenir l'artiste de chaque morceau — c'est la base de la
        classification par artiste (un artiste id="0" signifie "aucun
        artiste renseigné" et n'a pas de ligne correspondante).
        """
        table = self._table(TableType.ARTISTS)
        if table is None:
            return {}
        return dict(_parse_artist_row(self._buf, addr) for addr in _iter_table_rows(self._buf, self.header, table))

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

    def creer_playlist(self, nom: str, parent_id: str = "0", is_folder: bool = False) -> str:
        """Crée une nouvelle playlist (ou un dossier) et renvoie son nouvel id.

        `parent_id="0"` place la playlist à la racine. Contrairement aux
        suppressions, cette opération alloue de nouvelles lignes dans le
        fichier (et potentiellement une nouvelle page) : voir `_inserer_ligne`.
        """
        table_index = self._table_index(TableType.PLAYLIST_TREE)
        table = self.header.tables[table_index]

        if parent_id != "0":
            parents = _iter_table_row_locations(self._buf, self.header, table)
            if not any(_parse_playlist_tree_row(self._buf, loc.row_addr).id == parent_id for loc in parents):
                raise PdbFormatError(f"Dossier parent introuvable (id={parent_id}).")

        nouvel_id = _generer_nouvel_id(
            self._buf, self.header, TableType.PLAYLIST_TREE, lambda buf, addr: struct.unpack_from("<I", buf, addr + 0xC)[0]
        )

        row_bytes = struct.pack("<5I", int(parent_id), 0, 0, nouvel_id, 1 if is_folder else 0)
        row_bytes += _encode_device_sql_string(nom)

        _inserer_ligne(self._buf, self.header, table_index, row_bytes)
        return str(nouvel_id)

    def ajouter_morceau(self, playlist_id: str, track_id: str) -> int:
        """Ajoute un morceau (déjà présent dans la base) à la fin d'une playlist.

        Renvoie l'entry_index attribué. Lève PdbFormatError si la playlist ou
        le morceau n'existent pas, ou si le morceau est déjà dans la playlist
        (pas de doublon : correspond à la sémantique « ajouter/retirer » du
        cahier des charges, pas à une liste pouvant contenir plusieurs fois
        le même morceau).
        """
        tree_table = self._table(TableType.PLAYLIST_TREE)
        if tree_table is None or not any(
            _parse_playlist_tree_row(self._buf, loc.row_addr).id == playlist_id
            for loc in _iter_table_row_locations(self._buf, self.header, tree_table)
        ):
            raise PdbFormatError(f"Playlist introuvable (id={playlist_id}).")

        tracks_table = self._table(TableType.TRACKS)
        if tracks_table is not None:
            connu = any(
                struct.unpack_from("<I", self._buf, loc.row_addr + 0x48)[0] == int(track_id)
                for loc in _iter_table_row_locations(self._buf, self.header, tracks_table)
            )
            if not connu:
                raise PdbFormatError(f"Morceau introuvable dans la base (id={track_id}).")

        entries_table_index = self._table_index(TableType.PLAYLIST_ENTRIES)
        entries_table = self.header.tables[entries_table_index]

        max_entry_index = -1
        for loc in _iter_table_row_locations(self._buf, self.header, entries_table):
            entry = _parse_playlist_entry_row(self._buf, loc.row_addr)
            if entry.playlist_id == playlist_id:
                if entry.track_id == track_id:
                    raise PdbFormatError(f"Le morceau {track_id} est déjà dans la playlist {playlist_id}.")
                max_entry_index = max(max_entry_index, entry.entry_index)

        nouvel_entry_index = max_entry_index + 1
        row_bytes = struct.pack("<3I", nouvel_entry_index, int(track_id), int(playlist_id))
        _inserer_ligne(self._buf, self.header, entries_table_index, row_bytes)
        return nouvel_entry_index

    def enregistrer(self, chemin: str | Path | None = None) -> None:
        """Écrit le contenu (éventuellement modifié) sur le disque.

        Ne fait aucune sauvegarde elle-même : voir `rbmanager.backup` pour
        la copie de sécurité qui doit systématiquement précéder cet appel.
        """
        cible = Path(chemin) if chemin else self.path
        cible.write_bytes(bytes(self._buf))
