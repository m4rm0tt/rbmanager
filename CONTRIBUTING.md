# Contribuer / rebuilder rbmanager

## Structure du code

```
src/rbmanager/
  __init__.py     # métadonnées du package
  etape0.py       # étape 0 : script de validation (connexion + listing des playlists)
docs/
  cli-reference.md  # référence des commandes CLI et de leurs formats JSON
.github/workflows/
  build-windows.yml # build automatique de l'exécutable Windows via GitHub Actions
```

## Pourquoi le build passe par GitHub Actions et pas par Cowork directement

Le container Cowork utilisé pour développer ce projet tourne sous Linux,
alors que PyInstaller ne fait **pas** de cross-compilation : un build
lancé sous Linux produit un binaire Linux, inutilisable sur les
ordinateurs Windows visés. Le dépôt embarque donc un workflow GitHub
Actions (`.github/workflows/build-windows.yml`) qui se déclenche à chaque
push et compile l'exécutable sur une véritable machine Windows fournie par
GitHub. L'exécutable généré est récupéré depuis l'onglet **Actions** du
dépôt (section *Artifacts* du run correspondant) et c'est ce fichier qui
est livré, zippé avec la documentation.

## Rebuilder localement (si tu as un jour un accès Windows avec Python)

```bash
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --onefile --name rbmanager-etape0 \
  --hidden-import sqlalchemy.dialects.sqlite.pysqlcipher \
  --hidden-import sqlcipher3 \
  --hidden-import sqlcipher3.dbapi2 \
  --paths src \
  src/rbmanager/etape0.py
```

L'exécutable est généré dans `dist/rbmanager-etape0.exe` (ou sans
extension sous Linux/macOS).

## Rebuilder via GitHub Actions (méthode utilisée par défaut)

1. Pousser du code sur une branche du dépôt.
2. Le workflow `Build Windows executable` se déclenche automatiquement.
3. Une fois le run terminé, l'exécutable est disponible en téléchargement
   dans l'artifact `rbmanager-etape0-windows` du run.

## Conventions de code

- Commentaires en français, centrés sur le *pourquoi* (contraintes de
  `pyrekordbox`, particularités du schéma `export.pdb`, comportements
  paresseux de SQLAlchemy, etc.), pas sur la paraphrase du code.
- Toute commande CLI doit exposer un mode non-interactif complet
  (arguments en ligne de commande) et une sortie `--format json`, pour
  rester pilotable par un agent.
- Codes de sortie distincts par catégorie d'erreur (voir `docs/cli-reference.md`).
