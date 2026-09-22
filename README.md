# RekordboxPlaylistManager (rbmanager)

Logiciel portable pour gérer les playlists Rekordbox directement sur une
clé USB exportée — sans installation, pilotable en CLI par un humain ou
par un agent (Cowork).

## État actuel du projet : v1 complète

L'exécutable principal `rbmanager.exe` couvre l'ensemble du cahier des
charges v1 :
- **Lecture** : lister les playlists (`list-playlists`), afficher le
  contenu d'une playlist (`show-playlist`).
- **Écriture** (format historique DeviceSQL uniquement, voir plus bas),
  avec sauvegarde automatique horodatée avant chaque modification :
  créer une playlist ou un dossier (`create-playlist`), supprimer une
  playlist (`delete-playlist`), ajouter (`add-track`) ou retirer
  (`remove-track`) un morceau d'une playlist.
- **Tri semi-automatique à l'import** (`suggest-playlist`) : suggère une
  ou plusieurs playlists existantes pour un morceau, à partir de son
  genre, son BPM et son nom de fichier — ne modifie jamais rien tout
  seul, c'est une suggestion à confirmer.
- Un **menu interactif en texte** (lancé automatiquement sans argument,
  y compris en double-cliquant sur l'exécutable) pour un usage humain, en
  plus du mode non-interactif pour un agent/script — les deux appellent
  exactement le même code.
- Un **journal horodaté** (`logs/rbmanager.log` sur la clé) de toutes les
  actions effectuées, succès comme échecs.

Le diagnostic en lecture seule de l'étape 0 reste disponible séparément
via `rbmanager-etape0.exe`.

**Validé sur une vraie base Rekordbox** (742 morceaux, playlists jusqu'à
701 morceaux, tables réparties sur plus de 180 pages) : lecture des vraies
playlists/titres/métadonnées, et cycle complet créer → ajouter → retirer
→ supprimer testé sur une copie sans aucun risque pour la clé d'origine.

Limitation assumée : la suppression de **dossiers** (pas des playlists
simples) n'est pas prise en charge, pour limiter le risque (suppression
récursive plus complexe) — voir `docs/cli-reference.md`.

## ⚠️ Avertissements importants

- **Ferme toujours Rekordbox avant d'utiliser cet outil.** Rekordbox
  verrouille sa base tant qu'il tourne ; l'utiliser en même temps peut
  corrompre `export.pdb`.
- Les commandes d'écriture ne fonctionnent que sur le format historique
  DeviceSQL (CDJ/XDJ classiques, dont la XDJ-RX3) — voir la section
  « Deux formats d'export différents » plus bas. Sur le format
  SQLCipher (Device Library Plus), seule la lecture est disponible.
- Chaque écriture fait une sauvegarde automatique horodatée dans
  `backups/` à la racine de la clé, avant toute modification. Chaque
  action (lecture ou écriture) est aussi consignée dans
  `logs/rbmanager.log` à la racine de la clé.
- **Teste toujours une nouvelle version sur une playlist jetable** créée
  exprès, jamais directement sur tes vraies playlists, tant que tu n'as
  pas confirmé que ça fonctionne comme attendu chez toi.

## Utilisation (humain)

1. Branche ta clé USB Rekordbox (déjà éjectée du logiciel Rekordbox) et ferme Rekordbox.
2. Décompresse le zip livré — aucune installation requise.
3. Double-clique sur `rbmanager.exe` (ou lance-le depuis un terminal sans
   argument) : un menu en texte s'ouvre, te demande le chemin de la clé,
   puis propose les actions disponibles (lister, afficher, créer,
   ajouter/retirer un morceau, supprimer une playlist, suggérer une
   playlist pour un morceau).

Pour le diagnostic en lecture seule seul (étape 0), ou en ligne de
commande directe :

```bash
rbmanager-etape0.exe --usb E:\
rbmanager.exe list-playlists --usb E:\
```

(Remplace `E:\` par la lettre de lecteur de ta clé USB sous Windows, ou le
point de montage sous macOS/Linux, ex. `/Volumes/MA_CLE` ou
`/media/usb`.)

Tu peux aussi pointer directement vers le fichier ou son dossier parent :

```bash
rbmanager-etape0.exe --db-path "E:\PIONEER\rekordbox\export.pdb"
```

Le programme affiche la hiérarchie des playlists (dossiers inclus) trouvées
sur la clé.

## Utilisation (agent / mode non-interactif)

Toutes les commandes supportent une sortie JSON structurée via
`--format json`, pensée pour être consommée par un script ou un agent :

```bash
rbmanager-etape0.exe --usb E:\ --format json
```

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
        {"id": "2", "nom": "Speed Garage", "type": "playlist", "nb_morceaux": 12, "enfants": []}
      ]
    }
  ]
}
```

### Codes de sortie

| Code | Signification |
|------|----------------|
| 0    | Succès |
| 2    | Clé USB introuvable ou structure Rekordbox invalide (`PIONEER/rekordbox/export.pdb` absent) |
| 3    | `export.pdb` trouvé mais illisible (corrompu, copie incomplète, ou clé de déchiffrement non reconnue) |
| 4    | Rekordbox est actuellement lancé sur la machine — ferme-le d'abord |
| 10   | Erreur inattendue |

Voir `docs/cli-reference.md` pour le détail complet de chaque commande et
de son format de sortie JSON (référence pensée pour piloter l'outil via un
agent ou le futur skill Claude).

## Deux formats d'export différents

Rekordbox exporte en réalité deux formats binaires différents sous le nom
`export.pdb`, selon le matériel visé :

- **Format historique DeviceSQL** (non chiffré) : utilisé par les CDJ/XDJ
  classiques, dont la **XDJ-RX3**. `pyrekordbox` ne le supporte pas du
  tout ; rbmanager embarque son propre lecteur (`rbmanager.pdb_format`),
  basé sur la spécification communautaire de rétro-ingénierie (projet
  Deep Symmetry "Crate Digger"), faute de bibliothèque existante.
- **"Device Library Plus"** (SQLite chiffré SQLCipher) : pour du matériel
  plus récent (OPUS-QUAD, OMNIS-DUO, XDJ-AZ). Lu via `pyrekordbox`.

Le script détecte automatiquement lequel des deux formats est présent sur
ta clé (champ `format_detecte` dans la sortie JSON) — tu n'as rien à
préciser. Voir `docs/pdb-format.md` pour le détail technique du format
historique (structure des pages, calcul des offsets, sources utilisées).

## Suite du projet

v1 est complète. Restent, dans l'ordre du cahier des charges initial :
- **v1.5** : skill Claude documentant ces commandes pour un pilotage en
  langage naturel.
- **v2** : import de nouveaux morceaux audio vers la clé, gestion des
  métadonnées (si le temps le permet).

## Développement

Voir `CONTRIBUTING.md` pour la structure du code et comment rebuilder
l'exécutable.
