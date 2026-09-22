"""
Journal des actions de rbmanager, écrit sur la clé USB elle-même.

Contrainte du cahier des charges : « Logs clairs et horodatés dans un
fichier (logs/) pour que je puisse suivre après coup ce que l'agent a
fait sur ma clé. » Le journal vit à côté de `backups/`, à la racine de
la clé, pour rester consultable quel que soit l'ordinateur utilisé.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rbmanager.backup import racine_cle_usb

NOM_FICHIER = "rbmanager.log"


def _fichier_log(chemin_export_pdb: str | Path) -> Path:
    dossier = racine_cle_usb(chemin_export_pdb) / "logs"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / NOM_FICHIER


def consigner(chemin_export_pdb: str | Path, commande: str, details: str, succes: bool) -> None:
    """Ajoute une ligne horodatée au journal. N'échoue jamais bruyamment :
    un souci d'écriture du journal ne doit pas empêcher l'action elle-même
    de se terminer correctement (le journal est un confort, pas une garantie)."""
    try:
        horodatage = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        statut = "OK" if succes else "ERREUR"
        ligne = f"[{horodatage}] {statut:<6} {commande:<20} {details}\n"
        with open(_fichier_log(chemin_export_pdb), "a", encoding="utf-8") as f:
            f.write(ligne)
    except OSError:
        pass
