# Référence CLI — rbmanager

Document de référence pour piloter `rbmanager` via un agent (Cowork, skill
Claude) ou un script. Mis à jour au fil des versions ; ne contient pour
l'instant que l'étape 0.

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

## Commandes à venir (v1, non encore implémentées)

Cette section sera complétée au fur et à mesure : `list-playlists`,
`create-playlist`, `delete-playlist`, `add-track` / `remove-track`,
`show-playlist`, `suggest-playlist`. Le format restera cohérent avec celui
documenté ci-dessus (JSON structuré + codes de sortie distincts).
