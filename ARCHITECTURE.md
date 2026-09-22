# ARCHITECTURE — DJ Library Auto-Organizer

Traduction technique de `PROJECT_CONTEXT.md`. Lire ce dernier d'abord
pour le "pourquoi".

## 1. rbmanager : ce qui existe déjà (analysé avant d'écrire du code)

`rbmanager` (racine de ce dépôt) est une bibliothèque Python + CLI qui
lit et écrit `export.pdb`, le fichier binaire que Rekordbox exporte sur
une clé USB. Deux formats coexistent sous ce même nom de fichier :

- **DeviceSQL classique** (non chiffré, CDJ/XDJ dont la XDJ-RX3) : lu
  ET écrit, via un parseur maison (`rbmanager.pdb_format`) basé sur la
  spec communautaire Kaitai (Deep Symmetry "Crate Digger"). C'est le
  seul format sur lequel les opérations d'écriture existent.
- **SQLCipher "Device Library Plus"** (matériel récent) : lecture seule,
  via `pyrekordbox`.

Ce que rbmanager expose déjà (`src/rbmanager/`) :

| Module | Rôle |
|---|---|
| `pdb_format.py` | `PdbFile` : lecture des tables (`playlist_tree`, `playlist_entries`, `tracks`, `genres`, `keys`, et maintenant `artists`), écriture (bascule de bits de présence pour supprimer, insertion de nouvelles lignes en fin de table pour créer/ajouter). |
| `etape0.py` | Détection de format, résolution de chemin (`--usb`/`--db-path`), arbre des playlists, codes de sortie standardisés, gestion d'erreurs "métier" (`ErreurConnexion`). |
| `cli.py` | CLI non-interactive (`--format json`) : `list-playlists`, `show-playlist`, `create-playlist`, `delete-playlist`, `add-track`, `remove-track`, `suggest-playlist`. |
| `backup.py` | Sauvegarde horodatée d'`export.pdb` dans `<clé>/backups/` avant toute écriture. |
| `journal.py` | Log horodaté de chaque action dans `<clé>/logs/rbmanager.log`. |
| `suggest.py` | Heuristique transparente de suggestion de playlist (genre + BPM + nom de fichier) — ne modifie jamais rien, propose seulement. |

**Ce qui manquait, et bloquait tout le projet : l'extraction des
artistes.** `TrackInfo` n'exposait ni `artist_id`, ni aucune fonction
pour lire la table `artists`. Sans ça, il n'existe aucun moyen d'obtenir
l'artiste d'un morceau depuis `export.pdb`. Ajouté dans ce projet
(voir git log) :

- `TrackInfo.artist_id` (offset `+0x44` dans une ligne `tracks`, entre
  `album_id` `+0x40` et `id` `+0x48` — vérifié par recoupement avec les
  offsets déjà validés du projet sur une vraie base : `key_id` `+0x20`,
  `tempo` `+0x38`, `genre_id` `+0x3C`, `id` `+0x48` coïncident
  exactement avec la spec Kaitai communautaire, qui donne donc aussi
  `artist_id` avec confiance).
- `PdbFile.artist_names() -> dict[str, str]` : lit la table `artists`
  (`subtype`, `id` à `+0x04`, nom à un offset variable —
  `ofs_name_near` sur 1 octet à `+0x09`, ou `ofs_name_far` sur 2 octets
  à `+0x0A` si `subtype & 0x04`, cas des noms trop longs pour un offset
  court).

**Validé sur la vraie base de l'utilisateur** (742 tracks, 511 lignes
`artists`) : 0 `artist_id` orphelin (référençant un artiste inexistant),
seulement 3 morceaux sans artiste renseigné (`artist_id == 0`), noms
correctement décodés y compris accentués (`Ömer Faruk Bostan`) et
multi-artistes (`"Romeo Santos, Prince Royce"`, `"W&W, Dimitri Vegas &
Like Mike, Marnik"`). Cette dernière donnée confirme au passage la
nécessité du parsing des collaborations (§4 plus bas) et que le
séparateur `&` ne doit être reconnu qu'entouré d'espaces (sinon `W&W`
serait cassé en deux).

La couche SaaS n'a **jamais** besoin de réimplémenter la lecture du
format binaire : elle consomme `PdbFile` directement (en-process, le
sandbox de dev tourne sous Linux donc on ne peut de toute façon pas
utiliser les exécutables `.exe` PyInstaller — voir `CONTRIBUTING.md`).

## 2. Vue d'ensemble

```
                         CLOUD (MVP)
Browser (dark SaaS UI)
   │  upload export.pdb / preview / apply / chat
   ▼
FastAPI backend (saas/backend)
   │
   ├── LibraryService           orchestration haut niveau
   │     ├── ClassificationPipeline   Artist → Genre (§3)
   │     ├── OrganizationPlanner      construit/édite le plan (§5)
   │     └── ChatRuleEngine           langage naturel → édition du plan (§6)
   │
   └── LibraryProvider (interface)
         └── RbManagerAdapter
               └── rbmanager.pdb_format.PdbFile   (ce dépôt, en-process)
                     └── export.pdb (copie serveur du fichier uploadé)

                         LOCAL (futur, hors MVP)
Local Agent (sur la machine du DJ) ── USB Drive ── export.pdb
   │ parle au SaaS via la même API que le navigateur
```

Le MVP ne prétend jamais accéder à une clé USB depuis le cloud : on
upload `export.pdb`, on le traite côté serveur (copie de travail par
bibliothèque), et l'utilisateur retélécharge le fichier modifié pour le
recopier lui-même sur sa clé. Le futur Local Agent parlera la même API
HTTP que le navigateur ; `LibraryProvider`/`RbManagerAdapter` n'ont pas
besoin de changer pour ça.

## 3. Artist Classification Database

```sql
CREATE TABLE artist_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_name TEXT NOT NULL,               -- forme d'affichage (accents conservés)
    normalized_artist_name TEXT NOT NULL,    -- clé de recherche
    primary_genre TEXT NOT NULL,
    genres TEXT NOT NULL DEFAULT '[]',       -- JSON: liste de genres (multi-genre, §10 du contexte)
    confidence REAL NOT NULL DEFAULT 0.5,
    source TEXT NOT NULL,                    -- 'seed' | 'heuristic_fallback' | 'web_research' | 'manual'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX ix_artist_classifications_normalized ON artist_classifications(normalized_artist_name);
CREATE INDEX ix_artist_classifications_genre ON artist_classifications(primary_genre);
```

- **Index unique sur `normalized_artist_name`** : c'est la seule
  colonne de recherche du chemin chaud (Track → Artist → Genre). SQLite
  utilise cet index pour un lookup en O(log n), et surtout permet un
  **lookup batch en une seule requête** : `SELECT normalized_artist_name,
  primary_genre, ... FROM artist_classifications WHERE
  normalized_artist_name IN (?, ?, ..., ?)`.
- **Un seul fichier SQLite pour tout le produit** (pas par utilisateur) :
  c'est la base de connaissance partagée décrite en §6-7-27 du contexte
  — un artiste classifié par un utilisateur bénéficie à tous les
  suivants. `WAL mode` activé pour des lectures concurrentes rapides
  pendant qu'une écriture (nouvel artiste) a lieu.
- `genres` est stocké en JSON (`primary_genre` reste une colonne dédiée
  pour l'index et les requêtes simples ; `genres[]` est la surface
  d'extension multi-genre, non exploitée par le MVP au-delà du
  stockage).

## 4. Normalisation et découpage des artistes

`normalization.py` :

```python
def normalize_artist_name(raw: str) -> str:
    # 1. trim + collapse espaces multiples
    # 2. lowercase
    # 3. repli des accents (unicodedata NFKD, suppression des marques
    #    combinantes) — Ömer -> omer, POUR LA CLÉ SEULEMENT (le nom
    #    d'affichage garde ses accents)
    # 4. suppression de la ponctuation non significative (apostrophes,
    #    points) pour absorber "Ke$ha"/"Kesha"-like variations bénignes
    # 5. suppression des suffixes de collaboration résiduels isolés
    #    ("feat.", "ft." en fin de chaîne sans nom derrière)
```

`artist_split.py` :

```python
def split_artists(raw_artist_field: str) -> list[str]:
    # sépare sur, dans cet ordre de priorité (avec limites de mots) :
    #   " feat. " | " featuring " | " ft. " | " Ft. "
    #   " & " (espaces obligatoires — ne casse jamais "W&W")
    #   ", " | " x " | " X " | " vs " | " vs. " | " with "
    # renvoie la liste des noms individuels, DANS L'ORDRE, sans
    # jamais produire "Niska feat. Booba" comme UN SEUL nom.
    # names[0] == artiste principal (voir §5).
```

Validé empiriquement sur la vraie base (511 artistes réels) : les
séparateurs `", "` et `" & "` couvrent la quasi-totalité des cas
(`"Romeo Santos, Prince Royce"`, `"Kybba & Limitless Ft. Leftside"`,
`"Tiagz, Fuerza Regida & El Alfa"`), et le garde-fou espaces-obligatoires
autour de `&` protège bien les noms de duo du type `"W&W"`.

**Pas de fusion automatique par ressemblance** : `normalize_artist_name`
ne fait qu'une égalité exacte après normalisation déterministe — jamais
de distance de Levenshtein ni de similarité floue pour décider que deux
artistes DIFFÉRENTS sont le même (voir §3 du contexte).

## 5. Pipeline de classification (`classification/pipeline.py`)

```
extraire tracks (via LibraryProvider.list_tracks())
  → pour chaque track : split_artists(nom_artiste_brut) → artiste principal = [0]
  → normaliser tous les artistes principaux
  → dédupliquer → ensemble d'artistes uniques (742 tracks → ~184 pour la
    vraie base testée : rapport observé cohérent avec l'exemple du
    cahier des charges)
  → UNE requête batch : lookup(normalized_names) → {connus, inconnus}
  → pour chaque inconnu (une seule fois par artiste, jamais par morceau) :
      researcher.research(nom_affichage) → (genre, confidence, source)
      → upsert immédiat en DB (disponible pour la suite ET les futures
        bibliothèques, y compris avant la fin du traitement de CETTE
        bibliothèque)
  → chaque track reçoit primary_genre de son artiste principal
  → retour : ClassificationResult par track + stats
    (nb_tracks, nb_artistes_uniques, nb_connus, nb_recherches_effectuees)
```

Le pipeline ne connaît rien de l'implémentation du `Researcher` (voir
`classification/research.py`) : c'est le point d'extension pour brancher
une vraie recherche web/API plus tard sans toucher au reste. Le MVP
embarque `SeedListResearcher`, qui couvre les artistes cités en exemple
dans le cahier des charges (Niska/Gazo/Tiakola → Rap FR, Drake → Rap
US, Bad Bunny/Karol G → Reggaeton, Skream → Dubstep, etc.) et renvoie
`Other` à faible confiance pour le reste — remplaçable sans changer la
pipeline ni les tests (qui vérifient le **nombre d'appels**, pas
l'exactitude d'un moteur de recherche externe réel).

C'est ce point précis qui garantit la contrainte n°1 du produit :
`nb_recherches_effectuees ≈ nb_artistes_inconnus`, jamais `≈ nb_tracks`
(voir le test dédié 1000 tracks / 100 artistes).

## 6. Plan d'organisation et confirmation (`plan/`)

`OrganizationPlan` : structure immuable produite par
`build_plan(classification_results, genre_config)` —
`{"creates": [{"name": "Rap FR"}, ...], "moves": [{"genre": "Rap FR",
"track_ids": [...]}, ...]}`. Jamais appliqué directement : affiché comme
diff (`Preview Changes`), et seul `apply_plan(plan, library_provider)`
écrit réellement, après confirmation explicite (§14/§24 du contexte).

`apply_plan` :
1. **une seule sauvegarde** d'`export.pdb` avant toute écriture du plan
   entier (pas une sauvegarde par playlist/morceau — voir la note dans
   `PROJECT_CONTEXT.md`, déviation volontaire par rapport au comportement
   par-commande de la CLI `rbmanager`, pour rester praticable à 700+
   morceaux) ;
2. crée les playlists manquantes, ajoute les morceaux (idempotent : un
   morceau déjà présent n'est pas ré-ajouté) ;
3. enregistre le résultat dans `OrganizationRun` (historique, §20) avec
   le chemin de la sauvegarde ;
4. `undo(run_id)` restaure cette sauvegarde par-dessus `export.pdb`
   courant (avertit si des changements plus récents existent).

## 7. Chat = édition du plan, jamais exécution (`chat/rules.py`)

Interpréteur à règles pour le MVP (pas d'appel LLM externe dans ce
sandbox) : reconnaît des intentions ("mets X dans Y" → réassigne le
genre d'un artiste/genre source vers une cible, "crée une catégorie X" →
ajoute un genre custom, "sépare X et Y" → scinde un genre existant),
modifie la config de genres et/ou les classifications concernées, puis
**régénère le plan** via `build_plan`. Ne touche jamais
`LibraryProvider` directement. Conçu pour être remplacé par un vrai
appel LLM (ex. Claude) sans changer le reste : le contrat est
`interpret(message, current_config) -> ConfigPatch`.

## 8. Pourquoi pas de plugin/skill marketplace dédié au design

Recherche faite sur le catalogue de plugins disponible pour un
marketplace ou plugin "ecc" (demandé par l'utilisateur) : aucun
résultat. Le plus proche thématiquement (`design` d'Anthropic) est
orienté Figma/handoff d'équipe (MCP Figma/Notion/etc.), pas génération
de SaaS "moins IA". Le frontend du MVP est donc conçu à la main : dark
mode dense orienté data (tables, chiffres, activité), typographie
distincte, pas de dégradé violet générique ni d'iconographie
"assistant IA" — voir `saas/frontend/`.
