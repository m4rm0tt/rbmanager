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

### Codes de sortie spécifiques à `rbmanager`

| Code | Signification | Commandes concernées |
|------|----------------|------------------------|
| 5 | Format non supporté en écriture (SQLCipher / Device Library Plus) | delete-playlist, remove-track |
| 6 | Playlist introuvable | show-playlist, delete-playlist |
| 7 | Opération non supportée (ex : suppression d'un dossier) | delete-playlist |
| 8 | Le morceau n'était pas dans la playlist visée | remove-track |

Les codes 0, 2, 3, 4, 10 ont le même sens que pour `rbmanager-etape0`.

## Commandes à venir (v1, non encore implémentées)

`create-playlist`, `add-track`, `suggest-playlist`. Ces opérations
demandent d'allouer de nouvelles lignes dans le fichier (plus délicat que
les bascules de bit de présence utilisées par les commandes
ci-dessus) et n'ont pas encore été implémentées ni testées.
