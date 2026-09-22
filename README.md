# RekordboxPlaylistManager (rbmanager)

Logiciel portable pour gérer les playlists Rekordbox directement sur une
clé USB exportée — sans installation, pilotable en CLI par un humain ou
par un agent (Cowork).

## État actuel du projet

Au-delà de l'étape 0 (validation de la connexion, toujours disponible via
`rbmanager-etape0.exe`), le projet dispose maintenant d'un exécutable
principal `rbmanager.exe` avec :
- **Lecture** : lister les playlists (`list-playlists`), afficher le
  contenu d'une playlist (`show-playlist`).
- **Écriture** (format historique DeviceSQL uniquement, voir plus bas) :
  retirer un morceau d'une playlist (`remove-track`), supprimer une
  playlist (`delete-playlist`). Toujours précédée d'une sauvegarde
  automatique horodatée.
- Un **menu interactif en texte** (lancé automatiquement sans argument,
  y compris en double-cliquant sur l'exécutable) pour un usage humain, en
  plus du mode non-interactif pour un agent/script.

Pas encore disponibles : création de playlist, ajout de morceau, tri
semi-automatique à l'import (nécessitent d'allouer de nouvelles lignes
dans le fichier, plus délicat — voir `docs/cli-reference.md`).

## ⚠️ Avertissements importants

- **Ferme toujours Rekordbox avant d'utiliser cet outil.** Rekordbox
  verrouille sa base tant qu'il tourne ; l'utiliser en même temps peut
  corrompre `export.pdb`.
- Les commandes d'écriture ne fonctionnent que sur le format historique
  DeviceSQL (CDJ/XDJ classiques, dont la XDJ-RX3) — voir la section
  « Deux formats d'export différents » plus bas. Sur le format
  SQLCipher (Device Library Plus), seule la lecture est disponible.
- Chaque écriture fait une sauvegarde automatique horodatée dans
  `backups/` à la racine de la clé, avant toute modification.
- **Teste toujours une nouvelle version sur une playlist jetable** créée
  exprès, jamais directement sur tes vraies playlists, tant que tu n'as
  pas confirmé que ça fonctionne comme attendu chez toi.

## Utilisation (humain)

1. Branche ta clé USB Rekordbox (déjà éjectée du logiciel Rekordbox) et ferme Rekordbox.
2. Décompresse le zip livré — aucune installation requise.
3. Double-clique sur `rbmanager.exe` (ou lance-le depuis un terminal sans
   argument) : un menu en texte s'ouvre, te demande le chemin de la clé,
   puis propose les actions disponibles (lister, afficher, retirer un
   morceau, supprimer une playlist).

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
préciser.

## Pourquoi cette étape avant tout le reste ?

Le format historique n'étant pas officiellement documenté par Pioneer, et
aucune bibliothèque existante ne le prenant en charge pour l'écriture,
valider cette étape 0 sur ta propre clé est indispensable avant de
construire le reste du projet (v1 : création/suppression/modification de
playlists), qui devra écrire dans ce format avec des précautions
particulières (sauvegarde automatique systématique).

## Suite du projet

Voir le cahier des charges complet dans les issues/discussions du dépôt
pour le détail des versions v1 (CRUD playlists + tri semi-automatique),
v1.5 (skill Claude) et v2 (import de morceaux).

## Développement

Voir `CONTRIBUTING.md` pour la structure du code et comment rebuilder
l'exécutable.
