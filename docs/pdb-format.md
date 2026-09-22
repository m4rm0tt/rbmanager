# Format `export.pdb` (historique DeviceSQL)

Ce document résume le format binaire lu et écrit par `rbmanager.pdb_format`
pour les clés USB Rekordbox destinées aux CDJ/XDJ classiques (dont la
**XDJ-RX3**) — à ne pas confondre avec le format SQLite chiffré SQLCipher
("Device Library Plus"), utilisé par du matériel plus récent (OPUS-QUAD,
OMNIS-DUO, XDJ-AZ) et lu via `pyrekordbox`.

## Pourquoi un module maison plutôt qu'une bibliothèque existante

Ce format n'est **pas documenté officiellement par Pioneer**. Il a été
entièrement rétro-ingénié par la communauté (notamment Henry Betts et
Fabian Lesniak), puis formalisé par le projet **Deep Symmetry / Crate
Digger**. Aucune bibliothèque Python n'existe pour le lire ni l'écrire :
`pyrekordbox` (prévu initialement pour ce projet) ne supporte que le
format SQLCipher. Le projet Rust `rekordcrate` sait le lire mais pas
(ou très partiellement) l'écrire.

**Sources de référence utilisées** :
- Spécification en prose : <https://github.com/Deep-Symmetry/crate-digger/blob/main/doc/modules/ROOT/pages/exports.adoc>
- Spécification machine (Kaitai Struct) : <https://github.com/Deep-Symmetry/crate-digger/blob/master/src/main/kaitai/rekordbox_pdb.ksy>
- Implémentation Rust indépendante (pour recouper les calculs d'offsets) : <https://github.com/Holzhaus/rekordcrate>

⚠️ **La documentation en prose contient au moins une erreur constatée** :
elle place le tableau des offsets de chaînes (`ofs_strings`) d'une ligne
`tracks` à l'octet `0x64`, alors que c'est en réalité `0x5E` (vérifié à
la fois par recoupement avec la spec Kaitai et directement sur une vraie
base `export.pdb`). Voir le commentaire à côté de
`TRACK_OFS_STRINGS_OFFSET` dans `pdb_format.py`. **En cas de doute sur un
champ, la spec Kaitai (`.ksy`) fait foi, pas la prose**, et le plus fiable
reste de vérifier sur un vrai fichier.

## Vue d'ensemble

Le fichier est une suite de **pages de taille fixe** (`len_page`, en
général 4096 octets). La première page contient un en-tête qui liste les
tables présentes. Chaque table est une **liste chaînée de pages** de
cette même taille. Chaque page contient un tas (*heap*) dans lequel les
lignes sont ajoutées en avançant depuis le début, et un **index de
lignes** qui grandit depuis la fin de la page vers l'arrière, par
groupes de 16 entrées.

```
┌─────────────────────────────────────────────────────────┐
│ Page 0 : en-tête du fichier (len_page, pointeurs de table)│
├─────────────────────────────────────────────────────────┤
│ Page N : en-tête de page │ tas (lignes) →   ← index (grpes)│
├─────────────────────────────────────────────────────────┤
│ Page N+1 (page suivante de la même table, via next_page) │
└─────────────────────────────────────────────────────────┘
```

## En-tête du fichier (page 0)

| Offset | Taille | Champ | Description |
|--------|--------|-------|--------------|
| `0x00` | 4 | (zéros) | |
| `0x04` | 4 | `len_page` | Taille d'une page, en octets |
| `0x08` | 4 | `num_tables` | Nombre de tables |
| `0x0c` | 4 | `next_unused_page` | Informationnel ; **ne pas s'y fier pour allouer une nouvelle page** (voir plus bas) |
| `0x10` | 4 | (zéros) | |
| `0x14` | 4 | `sequence` | Compteur global incrémenté à chaque page modifiée |
| `0x18` | 4 | (zéros) | |
| `0x1c` | 16 × `num_tables` | pointeurs de table | Voir ci-dessous |

Pointeur de table (16 octets) : `type`(4) `empty_candidate`(4)
`first_page`(4) `last_page`(4), où `first_page`/`last_page` sont des
**index de page** (position en octets = `index × len_page`).

Types de table utilisés par rbmanager : `0`=tracks, `1`=genres, `5`=keys,
`7`=playlist_tree, `8`=playlist_entries. La liste complète est dans
`TableType` (`pdb_format.py`).

## En-tête de page (commun, 0x20 octets)

| Offset | Champ |
|--------|-------|
| `0x00` (4o) | (zéros) |
| `0x04` (4o) | `page_index` |
| `0x08` (4o) | `type` (type de table) |
| `0x0c` (4o) | `next_page` |
| `0x10` (4o) | `sequence` |
| `0x14` (4o) | (zéros) |
| `0x18` (3o) | `row_counts` : voir plus bas |
| `0x1b` (1o) | `page_flags` : bit 6 = page d'index (pas de lignes), bit 4 = contient des lignes supprimées |
| `0x1c` (2o) | `free_size` |
| `0x1e` (2o) | `used_size` |

Puis, pour une page de données (0x20-0x27) : `transaction_row_count`(2),
`transaction_row_index`(2), deux champs inconnus (2+2). **Le tas commence
à l'octet `0x28`** (`HEAP_START`).

### `row_counts` (3 octets à `0x18`, le point le plus piégeux du format)

Ces 3 octets encodent deux compteurs sur 24 bits au total, **en
little-endian, bits de poids faible en premier** :
- bits 0-12 (13 bits) : `num_row_offsets`, le nombre d'entrées d'index
  jamais désallouées (ne diminue jamais, même après une suppression).
- bits 13-23 (11 bits) : `num_rows_valid`, le nombre de lignes
  actuellement présentes.

⚠️ Une première lecture de la documentation en prose suggérait l'inverse
(poids fort/poids faible échangés). C'est en confrontant avec le code
Rust de `rekordcrate` (`PackedRowCounts { num_rows: B13, num_rows_valid:
B11 }`, où le premier champ déclaré occupe les bits de poids faible) que
l'ambiguïté a été levée.

## Index des lignes (groupes de 16, en partant de la fin de la page)

Chaque groupe fait exactement 36 octets et occupe, pour le groupe `g`
(0 = le plus proche de la fin de la page) :
`[len_page − 36×(g+1), len_page − 36×g[`, structuré ainsi (adresses
croissantes) : 16 offsets de ligne (2 octets chacun, du plus haut au
plus bas indice logique), puis `row_presence_flags` (2 octets, bit `k` =
ligne locale `k` présente), puis 2 octets non documentés (souvent appelés
"transaction flags").

Pour la ligne logique globale `i` : groupe `g = i // 16`, indice local
`k = i % 16`. L'adresse absolue de la ligne est
`page_start + 0x28 + offset_lu_dans_l_index` (si le bit de présence
correspondant est à 1 — sinon la ligne est supprimée et son contenu ne
doit pas être interprété).

## Chaînes DeviceSQL

Voir `_read_device_sql_string`/`_encode_device_sql_string` dans
`pdb_format.py`. Trois formats possibles, distingués par le premier
octet (`length_and_kind`) :
- **Courte ASCII** (bit 0 = 1) : longueur totale = `length_and_kind >> 1`,
  jusqu'à 126 octets de données.
- **Longue ASCII** (`length_and_kind == 0x40`) : longueur 16 bits sur 2
  octets, puis 1 octet de padding, puis les données.
- **Longue UTF-16LE** (`length_and_kind == 0x90`) : même structure
  d'en-tête, données en UTF-16LE (utilisé pour les noms accentués écrits
  par rbmanager).

## Lignes utilisées par rbmanager

- **`playlist_tree`** (20 octets fixes + nom) : `parent_id`(4)
  `unknown`(4) `sort_order`(4) `id`(4) `raw_is_folder`(4) puis le nom
  (chaîne DeviceSQL, toujours directement à l'offset `0x14`, jamais de
  pointeur indirect contrairement aux pistes/artistes/albums).
- **`playlist_entries`** (12 octets, taille fixe) : `entry_index`(4)
  `track_id`(4) `playlist_id`(4).
- **`tracks`** (voir `_parse_track_info`) : champs fixes jusqu'à l'octet
  `0x5E` (`key_id`@0x20, `tempo`@0x38 en BPM×100, `genre_id`@0x3C,
  `id`@0x48), puis un tableau de 21 offsets de chaînes à partir de
  `0x5E` (indice 17 = titre, 19 = nom de fichier, 20 = chemin complet).
- **`genres`**/**`labels`** (identiques) : `id`(4) puis nom.
- **`keys`** : `id`(4) `id2`(4, copie) puis nom.

## Écriture : allocation en pile (bump allocator)

`rbmanager` n'ajoute des lignes qu'à la **fin** de la dernière page d'une
table (jamais de réutilisation des trous laissés par des suppressions,
comme Rekordbox lui-même d'après la documentation — voir
`_inserer_ligne`). Si la page est pleine, une nouvelle page est ajoutée
**à la fin réelle du fichier** (`len(buf) // len_page`), jamais à
l'emplacement indiqué par `next_unused_page` : sur une vraie base
Rekordbox testée, ce champ vaut plus que le nombre réel de pages du
fichier (188 contre 186 pages réelles constatées), et s'y fier aurait
laissé un trou de pages non initialisées au milieu du fichier.

Les suppressions (`supprimer_playlist`, `retirer_morceau`) ne font que
basculer le bit de présence correspondant : c'est l'opération la plus
sûre du format, aucune réorganisation de données.

## Limitations connues de l'implémentation actuelle

- Pas de gestion des chaînes "far offset" (pointeur indirect) utilisées
  par les lignes `albums`/`artists`/`tags` pour les noms très longs :
  sans objet pour `playlist_tree` (toujours en accès direct), mais à
  garder en tête si une future version lit ces tables.
- Pas de récupération de l'espace laissé par les lignes supprimées
  (comme Rekordbox lui-même, d'après la doc).
- Pas de suppression récursive de dossiers.
