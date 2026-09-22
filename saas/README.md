# SaaS MVP — DJ Library Auto-Organizer

Voir `PROJECT_CONTEXT.md` et `ARCHITECTURE.md` à la racine du dépôt
avant de modifier quoi que ce soit ici : ils contiennent le cahier des
charges complet et sa traduction technique.

## Lancer en local

```bash
cd saas/backend
pip install -r requirements.txt
PYTHONPATH="$(pwd):$(pwd)/../../src" \
  python -m uvicorn app.main:app --reload --port 8000
```

Ouvrir http://localhost:8000 — le frontend statique (`saas/frontend/`)
est servi directement par FastAPI, aucune étape de build.

Par défaut, les données du produit (Artist Classification Database,
historique, bibliothèques uploadées) sont stockées dans `saas/backend/data/`
(ignoré par git). Personnalisable via `DJ_ORGANIZER_DATA_DIR`.

## Tests

```bash
cd saas/backend
pip install -r requirements.txt pytest fastapi[standard] httpx
PYTHONPATH="$(pwd):$(pwd)/../../src" python -m pytest tests/ -v
```

Réutilise `tests/pdb_builder.py` du dépôt rbmanager principal (voir
`pyproject.toml`, `pythonpath`) pour construire des fichiers
`export.pdb` synthétiques — aucune duplication de la logique de
construction du format binaire.

## Structure

```
saas/backend/app/
  normalization.py        Normalisation des noms d'artiste (clé de recherche)
  artist_split.py          Découpage des collaborations multi-artistes
  genres.py                 Genres par défaut, personnalisables
  classification/
    db_repo.py               Artist Classification Database (SQLite, indexée)
    research.py               Recherche d'artiste inconnu (interface pluggable)
    pipeline.py                Track -> Artist -> Genre, minimisant les recherches
  library/
    provider.py                LibraryProvider (interface)
    rbmanager_adapter.py         Implémentation au-dessus de rbmanager
    workspace.py                  Espace de travail serveur pour un upload
    service.py                     Orchestration lecture -> classification -> plan
  plan/
    config.py                     Genres/redirections/overrides éditables par le chat
    builder.py                     Construction du plan (jamais appliqué seul)
    apply.py                        Seule fonction qui écrit réellement
    history.py                       Historique des organisations + undo
  chat/
    rules.py                      Chat -> édition de config (jamais exécution directe)
  routes/                        Endpoints FastAPI
saas/frontend/                   UI statique (HTML/CSS/JS, pas de build)
```
