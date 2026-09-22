# PROJECT_CONTEXT — DJ Library Auto-Organizer (SaaS MVP)

Ce fichier est la mémoire persistante du projet : le cahier des charges
complet donné par l'utilisateur, à conserver et relire avant toute
modification de la couche `saas/`. Voir aussi `ARCHITECTURE.md` pour la
traduction technique de ces exigences.

## Objectif

Construire un MVP SaaS web qui transforme automatiquement une
bibliothèque Rekordbox désordonnée (ex : 700 morceaux dans une seule
playlist) en plusieurs playlists propres, classées par genre. **Ce n'est
pas un outil de création de sets DJ.**

```
700 morceaux → analyse des artistes → Niska/Gazo/Tiakola → Rap FR,
Drake → Rap US, Bad Bunny → Reggaeton, Skream → Dubstep, etc.
→ création automatique des playlists (Rap FR, Rap US, Reggaeton,
Dubstep, House, Techno, EDM, Shatta, Afro, Latino, ...)
```

## 1. Concept central : classification PAR ARTISTE, pas par morceau

La logique est `Artist → Genre`, jamais `Track → Genre` directement,
parce que l'objectif est de construire une base de connaissances
musicale réutilisable qui s'améliore avec le temps.

```
Track → Artist → recherche dans Artist Classification DB
  ├── connu → classification immédiate, aucune requête externe
  └── inconnu → recherche externe → genre déterminé → enregistré en DB
                → utilisé pour CE morceau ET tous les autres morceaux
                  du même artiste dans la bibliothèque
```

Ne jamais faire une recherche par morceau. Si Niska est déjà connu en
DB comme "Rap FR", tous ses morceaux (Réseaux, Médicament, Commando, Mr
Sal, Coco, ...) sont classés instantanément sans nouvelle requête.

## 2. Artist Classification Database (persistante)

Table dédiée aux artistes, pas aux morceaux :

```
ArtistClassification
  id
  artist_name              -- forme d'affichage (première vue)
  normalized_artist_name    -- clé de recherche, indexée UNIQUE
  primary_genre
  genres[]                  -- multi-genres (voir §10)
  confidence
  source                    -- d'où vient la classification
  created_at / updated_at
```

Exemple : `Niska → Rap FR, confidence 0.98, source web_search`.

## 3. Normalisation des artistes

Champ `normalized_artist_name` pour absorber `Niska` / `niska` / `NISKA`
/ `Niska feat.` / `Niska & ...` : lowercase, trim, suppression des
espaces multiples, repli des accents pour la clé de recherche (l'affichage
garde les accents), nettoyage des suffixes de collaboration évidents.
**Ne JAMAIS fusionner automatiquement deux artistes différents parce que
leurs noms se ressemblent** (pas de fuzzy-matching/Levenshtein pour la
fusion — seulement une égalité exacte sur la forme normalisée).

## 4. Indexation — vitesse de lookup prioritaire

Index unique sur `normalized_artist_name`. Le lookup doit être proche de
`SELECT genre FROM artist_classifications WHERE normalized_artist_name = ?`,
et en pratique **une seule requête batch** avec `WHERE normalized_artist_name
IN (...)` pour toute la bibliothèque, jamais une requête par morceau.

## 5. Pipeline : grouper par artiste AVANT toute recherche

```
Import Rekordbox → extraire tracks → extraire artistes → normaliser
→ dédupliquer → lookup batch en DB
  → artistes connus : classification immédiate
  → artistes inconnus : recherche externe → écrire en DB → classifier
    tous leurs morceaux
```

742 tracks → ~184 artistes uniques → au plus 184 recherches, souvent
beaucoup moins si des artistes sont déjà en base.

## 6. Minimiser les crédits / appels API au maximum

Jamais `700 tracks → 700 requêtes`. Toujours `700 tracks → ~180
artistes uniques → check DB locale → seuls les artistes inconnus
déclenchent une recherche`. Une fois un artiste connu, il reste connu
pour **toutes les bibliothèques futures**, y compris celles d'autres
utilisateurs (base de connaissance partagée).

## 7. Recherche d'un artiste inconnu

`Unknown artist → recherche → genre déterminé → confidence → sauvegarde
permanente`, avec la source enregistrée (pour savoir comment la
classification a été obtenue).

## 8. Artist → Genre, jamais Track → Genre

Répété pour insister : c'est le principe fondateur, la DB d'artistes
doit devenir de plus en plus utile au fil du temps et des utilisateurs.

## 9. Collaborations / artistes multiples

`Niska, Booba` ou `Niska feat. Booba` ne doivent JAMAIS devenir un seul
"nouvel artiste" `"Niska feat. Booba"`. Il faut extraire les artistes
individuels (Niska, Booba), les classifier, puis déterminer la
classification finale du morceau (MVP : genre de l'artiste principal =
premier de la liste). Séparateurs à gérer : `feat.`, `featuring`, `ft.`,
`,`, ` & ` (espaces autour, pour ne pas casser des noms de duo comme
`W&W`), ` x `, ` vs `, ` vs. `, ` with `.

## 10. Artistes multi-genres

Un artiste peut avoir plusieurs genres (`genres[]`) en plus d'un
`primary_genre`. Le MVP utilise `primary_genre` pour la playlist
principale, mais l'architecture doit permettre plusieurs genres à
l'avenir (ex : Drake → primary Rap US, genres [Rap US, R&B, Pop]).

## 11. Genres personnalisables

Ne pas hardcoder complètement les genres. Liste par défaut proposée :
Rap FR, Rap US, Afro, Amapiano, Reggaeton, Latino, Shatta, Dancehall,
House, Tech House, Techno, EDM, Dubstep, Drum & Bass, Pop, R&B, Rock,
Other. L'utilisateur doit pouvoir ajouter ses propres catégories
(White Girl Music, Classics, Warm Up, Commercial, Throwback, ...).

## 12. Interface de classification — aperçu avant modification

Après analyse, afficher un résumé (742 tracks, 184 artistes, 139 connus
en DB, 45 nouveaux recherchés) puis la répartition par genre proposée,
avec `[Preview Changes]` puis `[Organize Library]`.

## 13. Chat IA pour ajuster les règles

Le DJ peut discuter en langage naturel : "Trie ma bibliothèque par
genre.", "Mets le baile funk dans Latino.", "Je veux séparer House et
Tech House.", "Crée une catégorie White Girl Music.", "Tout ce qui est
Rap FR doit aller dans Rap FR." L'IA modifie la configuration de
classification et régénère un plan.

## 14. Chat ≠ exécution directe

L'IA ne modifie **jamais** directement la bibliothèque. Elle produit un
plan structuré (JSON : `create_playlist`, `add_tracks`, ...), affiché
sous forme de diff (`Create: + Rap FR ...`, `Move: 126 tracks → Rap
FR ...`) avec `[Cancel]` / `[Apply Changes]`. Confirmation explicite
utilisateur obligatoire avant toute écriture.

## 15. Basé sur rbmanager

Toute la couche de manipulation Rekordbox s'appuie sur
https://github.com/m4rm0tt/rbmanager (ce dépôt) — ne pas réimplémenter
ce qui existe déjà. Abstraction : `LibraryProvider` (interface) +
`RbManagerAdapter` (implémentation via rbmanager). Chaîne : AI Organizer
→ Library Service → RbManager Adapter → rbmanager → base Rekordbox.

## 16. Base Rekordbox réelle de l'utilisateur

L'utilisateur fournit sa vraie base (`export.pdb`, format DeviceSQL
classique, 742 morceaux, 511 artistes) pour les tests — ne jamais la
remplacer par des données fictives dans les tests automatisés (elle
n'est PAS committée dans le dépôt, données personnelles). Un Demo Mode
séparé peut exister pour les démonstrations publiques.

## 17. Architecture cloud + futur agent USB

Le SaaS tourne dans le cloud ; un navigateur ne peut pas accéder
directement à une clé USB locale. Pas de fausse architecture prétendant
lire `E:\` ou `/Volumes/...` depuis le serveur. MVP : upload d'un
`export.pdb`, traité côté serveur, téléchargement du fichier modifié.
Plus tard : Local Agent qui parle au SaaS et à la clé USB en local.

## 18. Performance

Doit tenir à 500 / 1000 / 5000 / 10000 morceaux sans faire exploser le
nombre de requêtes. Pipeline : import → extraction tracks → extraction
artistes uniques → normalisation → lookup batch → connus (instantané) /
inconnus (recherche groupée) → persistance → application → génération
des playlists. Requêtes batch (`IN (...)`) plutôt qu'une requête par
artiste. Index nécessaires sur `normalized_artist_name`.

## 19. Cache

Plusieurs niveaux : Artist Classification DB (persistant) + cache
applicatif + cache de requête. Ne jamais refaire une recherche externe
pour un artiste déjà classifié sans raison.

## 20. Historique

Chaque organisation est enregistrée (date, nb tracks analysés,
playlists créées). Undo si rbmanager le permet pour l'opération
concernée, sinon restauration depuis les backups.

## 21–22. Interface SaaS + page Artists

Dark mode, moderne, minimaliste, professionnel, orienté musique — pas
une interface générique d'IA. Sidebar : Library / Organizer / Playlists
/ Artists / Activity / Settings. Page Artists : recherche, filtre par
genre, édition manuelle (genre, confidence), voir la source, suppression,
fusion de variantes si nécessaire.

## 23. Apprentissage des corrections

Si l'utilisateur corrige `Niska: Rap FR → Afro`, demander confirmation :
appliquer à tous les morceaux de Niska + sauvegarder dans la DB globale
(`[Yes, remember]`) ou seulement pour cette bibliothèque
(`[Only this library]`).

## 24. Sécurité

Jamais d'opération destructive automatique : toujours `Analyze → Preview
→ Confirmation utilisateur → Apply`. Backup avant toute modification
quand c'est possible (voir `rbmanager.backup`).

## 25. Tests à couvrir

Normalisation des artistes, artistes dupliqués, lookup DB (simple et
batch), classification, morceaux multi-artistes, génération de
playlists, plan d'organisation, undo, adapter rbmanager. Test dédié :
1000 tracks / 100 artistes uniques / 80 déjà en DB / 20 inconnus →
recherches externes attendues ≈ 20, **pas** 1000.

## 26. Critère de réussite du MVP

Importer la vraie base Rekordbox → voir les morceaux → "Organize my
library" → extraction des artistes → vérification de la DB → recherche
seulement des artistes inconnus → sauvegarde des nouvelles
classifications → classification de tous les morceaux → aperçu →
confirmation → playlists réellement créées/modifiées → ajustements en
langage naturel → une deuxième organisation nettement plus rapide car la
DB connaît déjà les artistes.

## 27. Vision produit long terme

Plus d'utilisateurs → Artist Classification DB plus grande → plus
d'artistes déjà connus → moins de recherches/API calls → organisation
toujours plus rapide. La DB d'artistes est un actif central du produit,
pas un simple cache temporaire.

## 28. Méthode

Analyse complète de rbmanager AVANT le code (fait — voir
`ARCHITECTURE.md` §"rbmanager : ce qui existe déjà"), puis analyse de la
vraie base Rekordbox fournie, puis conception de l'Artist Classification
DB, des index, du pipeline, de la minimisation des appels, puis
implémentation.

## Décisions prises pendant l'implémentation (à ne pas re-décider)

- **rbmanager ne lisait pas les artistes avant ce projet** : `TrackInfo`
  n'exposait ni `artist_id`, ni aucun accès à la table `artists` du
  format DeviceSQL classique. C'était le blocage n°1 pour tout le reste
  du projet. Ajouté dans `src/rbmanager/pdb_format.py`
  (`TRACK_ARTIST_ID_OFFSET = 0x44`, `PdbFile.artist_names()`),
  offsets vérifiés par recoupement avec la spec Kaitai communautaire
  ET validés sur la vraie base de l'utilisateur (742 tracks, 511
  artistes, 0 référence orpheline). Voir `docs/pdb-format.md`.
- La classification par artiste ne fonctionne aujourd'hui que sur le
  format DeviceSQL classique (le seul supporté en écriture par
  rbmanager de toute façon) — cohérent avec la limitation déjà
  documentée de rbmanager.
- Le "researcher" externe (étape "recherche d'un artiste inconnu") est
  conçu comme une interface pluggable (`ArtistResearcher`) : le MVP
  embarque une implémentation heuristique/seed-list locale (pas d'appel
  réseau non maîtrisé depuis ce sandbox), mais le pipeline ne fait
  strictement aucune hypothèse sur son implémentation — une vraie
  recherche web/API peut être branchée sans toucher au pipeline. C'est
  ce point d'interface qui est testé pour garantir "recherches ≈
  artistes inconnus, pas ≈ morceaux", pas l'exactitude d'un vrai moteur
  de recherche.
- Aucune recherche marketplace pour un plugin/skill nommé "ecc" n'a
  donné de résultat (voir conversation) : le design de l'interface SaaS
  a donc été fait à la main, sans plugin dédié, en évitant
  délibérément les clichés visuels "IA générique" (dégradés violets,
  tout arrondi, emojis).
