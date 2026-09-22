# Référence CLI — rbmanager

Document de référence pour piloter `rbmanager` via un agent (Cowork, skill
Claude) ou un script. Mis à jour au fil des versions.

## Deux exécutables

- `rbmanager-etape0.exe` : diagnostic en lecture seule (garde son rôle
  historique de validation, voir plus bas).
- `rbmanager.exe` : l'exécutable principal. **Lancé sans argument, il
  ouvre un menu interactif en texte** (pour un humain — fonctionne même
  en double-cliquant dessus). **Lancé avec une sous-commande et des
  arguments, il fonctionne en mode non-interactif** (pour un agent ou un
  script) avec sortie JSON disponible sur `--format json` : c'est ce mode
  qui est documenté ci-dessous, commande par commande. Le menu interactif
  appelle exactement les mêmes fonctions en interne, le comportement est
  donc garanti identique dans les deux modes.

## `rbmanager list-playlists`

Équivalent de `rbmanager-etape0` (voir plus bas), mais intégré à
l'exécutable principal.

```
rbmanager.exe list-playlists --usb D:\ --format json
```

Mêmes arguments et même format de sortie que `rbmanager-etape0`
ci-dessous (sans le champ `nb_playlists_racine`, remplacé par la
longueur de la liste `playlists`).

## `rbmanager show-playlist`

Affiche le contenu (morceaux, dans l'ordre) d'une playlist.

| Argument | Obligatoire | Description |
|----------|-------------|--------------|
| `--playlist-id` | Oui | ID de la playlist (voir `list-playlists`). |
| `--usb` / `--db-path` | Oui (un des deux) | Comme pour `list-playlists`. |
| `--format` | Non | `text` ou `json`. |

Sortie JSON :
```json
{
  "succes": true,
  "playlist_id": "10",
  "nb_morceaux": 3,
  "morceaux": [
    {"id": "111", "titre": "Nom du morceau"},
    {"id": "222", "titre": "Autre morceau"}
  ]
}
```

Si `titre` vaut `"(titre inconnu)"`, la table `tracks` ne contenait pas
d'entrée pour cet ID (ne devrait pas arriver sur une base saine).

## `rbmanager-etape0`

Se connecte à `export.pdb` sur une clé USB Rekordbox et liste les
playlists existantes (lecture seule, aucune écriture).

### Arguments

| Argument      | Obligatoire | Description |
|---------------|-------------|--------------|
| `--usb`       | Oui (ou `--db-path`) | Racine de la clé USB (ex: `E:\` sous Windows, `/media/cle-usb` sous Linux). Le script cherche `PIONEER/rekordbox/export.pdb` en dessous. |
| `--db-path`   | Oui (ou `--usb`) | Chemin direct vers `export.pdb`, ou vers son dossier parent. |
| `--key`       | Non | Clé SQLCipher à utiliser si la clé de déchiffrement automatique de `pyrekordbox` échoue (versions très récentes de Rekordbox). |
| `--format`    | Non (défaut `text`) | `text` (lisible humain) ou `json` (sortie structurée sur stdout). |

`--usb` et `--db-path` sont mutuellement exclusifs (exactement un des deux
doit être fourni).

### Sortie JSON (`--format json`) — succès

```json
{
  "succes": true,
  "chemin_export_pdb": "E:\\PIONEER\\rekordbox\\export.pdb",
  "nb_playlists_racine": 2,
  "playlists": [
    {
      "id": "1",
      "nom": "Genres",
      "type": "dossier",
      "nb_morceaux": 0,
      "enfants": [
        {
          "id": "2",
          "nom": "Speed Garage",
          "type": "playlist",
          "nb_morceaux": 12,
          "enfants": []
        }
      ]
    }
  ]
}
```

- `type` vaut `"playlist"`, `"dossier"` ou `"playlist_intelligente"`.
- `enfants` contient récursivement les sous-playlists/sous-dossiers (les
  dossiers Rekordbox peuvent être imbriqués).
- `nb_morceaux` vaut toujours `0` pour un `"dossier"` (les dossiers ne
  contiennent pas directement de morceaux).

### Sortie JSON — échec

```json
{
  "succes": false,
  "erreur": "message clair en français décrivant la cause",
  "code_sortie": 2
}
```

### Codes de sortie

| Code | Constante            | Signification |
|------|-----------------------|----------------|
| 0    | `EXIT_OK`             | Succès |
| 2    | `EXIT_CLE_INTROUVABLE`| `export.pdb` introuvable à l'emplacement attendu, ou structure de clé invalide |
| 3    | `EXIT_BASE_CORROMPUE` | Fichier trouvé mais illisible (corrompu, copie incomplète, version Rekordbox non supportée) |
| 4    | `EXIT_REKORDBOX_OUVERT` | Rekordbox est lancé sur la machine et verrouille la base |
| 10   | `EXIT_ERREUR_INCONNUE`| Erreur imprévue (voir le message pour le détail technique) |

### Exemples d'enchaînement pour un agent

```bash
# 1. Vérifier que la clé est valide et lister ce qu'elle contient
rbmanager-etape0.exe --usb E:\ --format json
# -> si code_sortie == 2 : demander à l'utilisateur de vérifier l'export Rekordbox
# -> si code_sortie == 4 : demander à l'utilisateur de fermer Rekordbox puis réessayer
# -> si succes == true : exploiter le champ "playlists" pour la suite
```

## `rbmanager delete-playlist`

Supprime une playlist (pas un dossier) et tous les morceaux qu'elle
contient. **Écrit sur la clé** : fait systématiquement une sauvegarde
horodatée d'export.pdb dans `backups/` avant toute modification. Ne
fonctionne que sur le format historique DeviceSQL (voir `rbmanager-etape0`
pour savoir quel format ta clé utilise).

| Argument | Obligatoire | Description |
|----------|-------------|--------------|
| `--playlist-id` | Oui | ID de la playlist à supprimer (voir la sortie de `rbmanager-etape0`). |
| `--usb` / `--db-path` | Oui (un des deux) | Comme pour `rbmanager-etape0`. |
| `--format` | Non | `text` ou `json`. |

Sortie JSON (succès) :
```json
{
  "succes": true,
  "message": "Playlist 10 supprimée (3 morceau(x) retiré(s) avec elle).",
  "playlist_id": "10",
  "nb_morceaux_retires": 3,
  "backup": "E:\\backups\\export_pdb_20260922_083259.pdb"
}
```

## `rbmanager remove-track`

Retire un morceau d'une playlist (la playlist et le morceau restent dans
la base, seule l'association est supprimée). Même politique de
sauvegarde automatique que `delete-playlist`.

| Argument | Obligatoire | Description |
|----------|-------------|--------------|
| `--playlist-id` | Oui | ID de la playlist. |
| `--track-id` | Oui | ID du morceau à retirer. |
| `--usb` / `--db-path` | Oui (un des deux) | Comme pour `rbmanager-etape0`. |
| `--format` | Non | `text` ou `json`. |

## `rbmanager create-playlist`

Crée une nouvelle playlist, ou un dossier. **Écrit sur la clé** (avec
sauvegarde automatique). Contrairement à `delete-playlist`/`remove-track`,
cette commande alloue de nouvelles lignes dans le fichier (et
potentiellement une nouvelle page si celle en cours est pleine) — voir
`docs/pdb-format.md` pour le détail de cette allocation.

| Argument | Obligatoire | Description |
|----------|-------------|--------------|
| `--name` | Oui | Nom de la playlist ou du dossier. |
| `--parent-id` | Non (défaut `0`, la racine) | ID du dossier parent, pour créer une sous-playlist/sous-dossier. |
| `--dossier` | Non | Créer un dossier plutôt qu'une playlist. |
| `--usb` / `--db-path` | Oui (un des deux) | Comme pour `list-playlists`. |
| `--format` | Non | `text` ou `json`. |

Sortie JSON (succès) :
```json
{
  "succes": true,
  "message": "Playlist « Nouvelle Playlist » créé(e) (id=42).",
  "playlist_id": "42",
  "backup": "E:\\backups\\export_pdb_20260922_090111.pdb"
}
```

Les identifiants sont attribués par rbmanager (max des ids existants + 1,
y compris ceux des playlists supprimées, pour ne jamais réutiliser un id)
: ne pas essayer de choisir l'id vous-même.

## `rbmanager add-track`

Ajoute un morceau (déjà présent dans la table `tracks` de la base) à la
fin d'une playlist existante. **Écrit sur la clé** (avec sauvegarde
automatique). Refuse d'ajouter un doublon (le même morceau deux fois dans
la même playlist).

| Argument | Obligatoire | Description |
|----------|-------------|--------------|
| `--playlist-id` | Oui | ID de la playlist cible. |
| `--track-id` | Oui | ID du morceau à ajouter. |
| `--usb` / `--db-path` | Oui (un des deux) | Comme pour `list-playlists`. |
| `--format` | Non | `text` ou `json`. |

Sortie JSON (succès) :
```json
{
  "succes": true,
  "message": "Morceau 444 ajouté à la playlist 10.",
  "playlist_id": "10",
  "track_id": "444",
  "entry_index": 3,
  "backup": "E:\\backups\\export_pdb_20260922_090046.pdb"
}
```

## `rbmanager suggest-playlist`

Tri semi-automatique à l'import : propose une ou plusieurs playlists
existantes pour un morceau, à partir de son genre, son BPM et le nom de
son fichier audio, comparés à ceux des morceaux déjà présents dans chaque
playlist. **Ne modifie jamais rien** — c'est une suggestion, à confirmer
ensuite via `add-track` (ou via le menu interactif, qui propose de le
faire directement). Voir `rbmanager.suggest` pour le détail de
l'heuristique (transparente : chaque suggestion explique sa raison).

| Argument | Obligatoire | Description |
|----------|-------------|--------------|
| `--track-id` | Oui | ID du morceau à trier. |
| `--usb` / `--db-path` | Oui (un des deux) | Comme pour `list-playlists`. |
| `--format` | Non | `text` ou `json`. |

Sortie JSON :
```json
{
  "succes": true,
  "track_id": "999",
  "suggestions": [
    {
      "playlist_id": "10",
      "nom": "Speed Garage Sets",
      "score": 1.85,
      "raisons": [
        "genre « Speed Garage » partagé par 100% des morceaux de la playlist",
        "BPM proche de la moyenne de la playlist (130, écart de 1.0)"
      ]
    }
  ],
  "nom_suggere": null
}
```

Si `suggestions` est vide, `nom_suggere` peut contenir un nom de playlist
suggéré (basé sur le genre du morceau) pour en créer une nouvelle — ou
`null` si pas assez d'information.

### Exemple d'enchaînement pour un agent (tri semi-automatique)

```bash
# 1. Demander une suggestion (ne modifie rien)
rbmanager.exe suggest-playlist --usb E:\ --track-id 999 --format json
# 2. Si "suggestions" contient un résultat pertinent, confirmer avec l'utilisateur puis :
rbmanager.exe add-track --usb E:\ --playlist-id 10 --track-id 999 --format json
# 3. Si "suggestions" est vide et "nom_suggere" est renseigné, proposer de créer la playlist :
rbmanager.exe create-playlist --usb E:\ --name "Ambient" --format json
rbmanager.exe add-track --usb E:\ --playlist-id <id renvoyé> --track-id 999 --format json
```

### Codes de sortie spécifiques à `rbmanager`

| Code | Signification | Commandes concernées |
|------|----------------|------------------------|
| 5 | Format non supporté en écriture (SQLCipher / Device Library Plus) | delete-playlist, remove-track, create-playlist, add-track, suggest-playlist |
| 6 | Playlist, dossier parent ou morceau introuvable | show-playlist, delete-playlist, create-playlist, add-track, suggest-playlist |
| 7 | Opération non supportée (ex : suppression d'un dossier) | delete-playlist |
| 8 | Le morceau n'était pas dans la playlist visée | remove-track |
| 9 | Le morceau est déjà dans la playlist visée | add-track |

Les codes 0, 2, 3, 4, 10 ont le même sens que pour `rbmanager-etape0`.

## Journal des actions

Chaque commande (lecture et écriture) ajoute une ligne horodatée dans
`<racine de la clé>/logs/rbmanager.log`, y compris en cas d'échec. Ce
fichier permet de suivre après coup ce qui a été fait sur la clé, y
compris par un agent en mode non-interactif.

## Limitations connues (au-delà de la v1)

- La suppression de **dossiers** n'est pas prise en charge (seulement les
  playlists simples) : la suppression récursive d'une hiérarchie entière
  est un cas plus risqué qui n'a pas été jugé prioritaire pour la v1.
- Les commandes d'écriture ne fonctionnent que sur le format historique
  DeviceSQL, pas sur le format SQLCipher (Device Library Plus).
