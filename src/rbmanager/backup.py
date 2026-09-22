"""
Sauvegarde automatique d'export.pdb avant toute écriture.

Contrainte non négociable du projet : jamais d'écriture sur la clé sans
une copie de sauvegarde horodatée préalable dans un dossier `backups/` à
la racine de la clé USB.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


def racine_cle_usb(chemin_export_pdb: str | Path) -> Path:
    """Remonte de export.pdb (usb/PIONEER/rekordbox/export.pdb) vers la racine de la clé."""
    chemin = Path(chemin_export_pdb)
    return chemin.parent.parent.parent


def sauvegarder(chemin_export_pdb: str | Path) -> Path:
    """Copie export.pdb dans <racine_cle>/backups/export_pdb_YYYYMMDD_HHMMSS.pdb.

    Renvoie le chemin de la copie créée. Lève FileNotFoundError si le
    fichier source n'existe pas (ne devrait pas arriver si appelé après
    `verifier_structure_cle`).
    """
    chemin = Path(chemin_export_pdb)
    dossier_backups = racine_cle_usb(chemin) / "backups"
    dossier_backups.mkdir(parents=True, exist_ok=True)

    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    cible = dossier_backups / f"export_pdb_{horodatage}.pdb"
    # Évite d'écraser une sauvegarde existante si deux appels tombent la même seconde.
    compteur = 1
    while cible.exists():
        cible = dossier_backups / f"export_pdb_{horodatage}_{compteur}.pdb"
        compteur += 1

    shutil.copy2(chemin, cible)
    return cible
