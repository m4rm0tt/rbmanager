"""
Menu interactif en texte pour rbmanager.

Lancé automatiquement quand l'exécutable est démarré sans argument (donc
en particulier en double-cliquant dessus sous Windows). N'implémente
aucune logique propre : chaque action appelle exactement les mêmes
fonctions que le mode non-interactif (`rbmanager.cli`), pour garantir un
comportement identique entre les deux modes — voir docs/cli-reference.md
pour la référence de ces fonctions côté agent.
"""

from __future__ import annotations

from pathlib import Path

from rbmanager.backup import sauvegarder
from rbmanager.etape0 import (
    ErreurConnexion,
    afficher_texte,
    classifier_exception,
    contenu_playlist_classic,
    contenu_playlist_sqlcipher,
    detecter_format,
    lister_playlists,
    lister_playlists_classic,
    ouvrir_base,
    resoudre_chemin_export_pdb,
    verifier_structure_cle,
)
from rbmanager.pdb_format import PdbFile, PdbFormatError

NOM_FORMAT = {
    "classic": "historique DeviceSQL (CDJ/XDJ classiques)",
    "sqlcipher": "SQLCipher (Device Library Plus)",
}


def _demander_cle_usb() -> tuple[Path, str] | tuple[None, None]:
    """Demande le chemin de la clé jusqu'à en obtenir un valide, ou 'q' pour quitter."""
    while True:
        reponse = input("\nChemin racine de la clé USB (ex: D:\\), ou 'q' pour quitter : ").strip()
        if reponse.lower() in ("q", "quitter", "quit"):
            return None, None
        if not reponse:
            continue
        try:
            chemin = resoudre_chemin_export_pdb(reponse, None)
            verifier_structure_cle(chemin)
        except ErreurConnexion as exc:
            print(f"\n⚠ {exc}\n")
            continue
        format_detecte = detecter_format(chemin)
        print(f"\nConnexion réussie : {chemin}")
        print(f"Format détecté : {NOM_FORMAT[format_detecte]}\n")
        return chemin, format_detecte


def _obtenir_playlists(chemin: Path, format_detecte: str):
    """Renvoie la liste des InfoPlaylist, en gérant l'ouverture/fermeture pour le format SQLCipher."""
    if format_detecte == "classic":
        return lister_playlists_classic(chemin)
    db = ouvrir_base(chemin, None)
    try:
        return lister_playlists(db)
    except Exception as exc:  # noqa: BLE001
        raise classifier_exception(exc) from exc
    finally:
        db.close()


def _obtenir_contenu(chemin: Path, format_detecte: str, playlist_id: str):
    if format_detecte == "classic":
        return contenu_playlist_classic(chemin, playlist_id)
    db = ouvrir_base(chemin, None)
    try:
        return contenu_playlist_sqlcipher(db, playlist_id)
    except ErreurConnexion:
        raise
    except Exception as exc:  # noqa: BLE001
        raise classifier_exception(exc) from exc
    finally:
        db.close()


def _action_lister(chemin: Path, format_detecte: str) -> None:
    try:
        playlists = _obtenir_playlists(chemin, format_detecte)
    except ErreurConnexion as exc:
        print(f"\n⚠ {exc}")
        return
    print()
    if not playlists:
        print("Aucune playlist trouvée sur cette clé.")
    else:
        afficher_texte(playlists)


def _action_afficher_playlist(chemin: Path, format_detecte: str) -> None:
    playlist_id = input("ID de la playlist à afficher : ").strip()
    if not playlist_id:
        return
    try:
        morceaux = _obtenir_contenu(chemin, format_detecte, playlist_id)
    except ErreurConnexion as exc:
        print(f"\n⚠ {exc}")
        return
    print()
    if not morceaux:
        print("Cette playlist ne contient aucun morceau.")
    else:
        for i, m in enumerate(morceaux, start=1):
            print(f"{i:>3}. {m.titre}  (id={m.id})")


def _action_retirer_morceau(chemin: Path, format_detecte: str) -> None:
    if format_detecte != "classic":
        print("\n⚠ La modification n'est pour l'instant possible que sur le format historique DeviceSQL.")
        return
    playlist_id = input("ID de la playlist : ").strip()
    track_id = input("ID du morceau à retirer : ").strip()
    if not playlist_id or not track_id:
        return
    confirmation = input(f"Confirmer le retrait du morceau {track_id} de la playlist {playlist_id} ? (o/N) : ").strip().lower()
    if confirmation != "o":
        print("Annulé.")
        return
    try:
        db = PdbFile(chemin)
        trouve = db.retirer_morceau(playlist_id, track_id)
        if not trouve:
            print(f"\n⚠ Le morceau {track_id} n'était pas présent dans la playlist {playlist_id}.")
            return
        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except (PdbFormatError, ErreurConnexion, OSError) as exc:
        print(f"\n⚠ {exc}")
        return
    print(f"\n✔ Morceau {track_id} retiré de la playlist {playlist_id}.")
    print(f"  Sauvegarde créée : {chemin_backup}")


def _action_supprimer_playlist(chemin: Path, format_detecte: str) -> None:
    if format_detecte != "classic":
        print("\n⚠ La modification n'est pour l'instant possible que sur le format historique DeviceSQL.")
        return
    playlist_id = input("ID de la playlist à supprimer : ").strip()
    if not playlist_id:
        return

    # On affiche le nom avant de demander confirmation, pour éviter de
    # supprimer la mauvaise playlist par erreur de frappe sur l'ID.
    try:
        playlists = lister_playlists_classic(chemin)
    except ErreurConnexion as exc:
        print(f"\n⚠ {exc}")
        return

    def _trouver(playlists, pid):
        for p in playlists:
            if p.id == pid:
                return p
            trouve = _trouver(p.enfants, pid)
            if trouve:
                return trouve
        return None

    cible = _trouver(playlists, playlist_id)
    if cible is None:
        print(f"\n⚠ Playlist introuvable (id={playlist_id}).")
        return
    if cible.type == "dossier":
        print("\n⚠ La suppression de dossiers n'est pas encore prise en charge.")
        return

    print(f"\nPlaylist visée : « {cible.nom} » ({cible.nb_morceaux} morceau(x)).")
    confirmation = input("Cette action est irréversible (mais une sauvegarde sera faite). Confirmer ? (o/N) : ").strip().lower()
    if confirmation != "o":
        print("Annulé.")
        return

    try:
        db = PdbFile(chemin)
        nb_retires = db.supprimer_playlist(playlist_id)
        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except (PdbFormatError, ErreurConnexion, OSError) as exc:
        print(f"\n⚠ {exc}")
        return
    print(f"\n✔ Playlist « {cible.nom} » supprimée ({nb_retires} morceau(x) retiré(s) avec elle).")
    print(f"  Sauvegarde créée : {chemin_backup}")


def _boucle_menu(chemin: Path, format_detecte: str) -> None:
    ecriture_possible = format_detecte == "classic"
    while True:
        print("\n=== RekordboxPlaylistManager ===")
        print(f"Clé : {chemin}  —  format : {NOM_FORMAT[format_detecte]}")
        print("1. Lister les playlists")
        print("2. Afficher le contenu d'une playlist")
        if ecriture_possible:
            print("3. Retirer un morceau d'une playlist")
            print("4. Supprimer une playlist")
        else:
            print("(Modification indisponible pour ce format pour l'instant)")
        print("0. Changer de clé USB / quitter")

        choix = input("\nChoix : ").strip()
        if choix == "1":
            _action_lister(chemin, format_detecte)
        elif choix == "2":
            _action_afficher_playlist(chemin, format_detecte)
        elif choix == "3" and ecriture_possible:
            _action_retirer_morceau(chemin, format_detecte)
        elif choix == "4" and ecriture_possible:
            _action_supprimer_playlist(chemin, format_detecte)
        elif choix == "0":
            return
        else:
            print("Choix invalide.")


def lancer_menu_interactif() -> int:
    print("=== RekordboxPlaylistManager ===")
    print("Ferme Rekordbox avant toute utilisation (lecture ou écriture).\n")
    try:
        while True:
            chemin, format_detecte = _demander_cle_usb()
            if chemin is None:
                print("\nAu revoir.")
                return 0
            _boucle_menu(chemin, format_detecte)
    except (EOFError, KeyboardInterrupt):
        print("\n\nAu revoir.")
        return 0
