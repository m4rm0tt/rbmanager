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
from rbmanager.journal import consigner
from rbmanager.pdb_format import PdbFile, PdbFormatError
from rbmanager.suggest import suggerer_playlists_classic

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
        consigner(chemin, "remove-track", f"playlist_id={playlist_id} track_id={track_id} — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(chemin, "remove-track", f"playlist_id={playlist_id} track_id={track_id}, backup={chemin_backup}", succes=True)
    print(f"\n✔ Morceau {track_id} retiré de la playlist {playlist_id}.")
    print(f"  Sauvegarde créée : {chemin_backup}")


def _action_ajouter_morceau(chemin: Path, format_detecte: str) -> None:
    if format_detecte != "classic":
        print("\n⚠ La modification n'est pour l'instant possible que sur le format historique DeviceSQL.")
        return
    playlist_id = input("ID de la playlist : ").strip()
    track_id = input("ID du morceau à ajouter (doit déjà être dans la base) : ").strip()
    if not playlist_id or not track_id:
        return
    try:
        db = PdbFile(chemin)
        entry_index = db.ajouter_morceau(playlist_id, track_id)
        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except (PdbFormatError, ErreurConnexion, OSError) as exc:
        consigner(chemin, "add-track", f"playlist_id={playlist_id} track_id={track_id} — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(
        chemin, "add-track", f"playlist_id={playlist_id} track_id={track_id} -> entry_index={entry_index}, backup={chemin_backup}", succes=True
    )
    print(f"\n✔ Morceau {track_id} ajouté à la playlist {playlist_id}.")
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
        consigner(chemin, "delete-playlist", f"playlist_id={playlist_id} — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(
        chemin, "delete-playlist", f"playlist_id={playlist_id}, {nb_retires} morceau(x) retiré(s), backup={chemin_backup}", succes=True
    )
    print(f"\n✔ Playlist « {cible.nom} » supprimée ({nb_retires} morceau(x) retiré(s) avec elle).")
    print(f"  Sauvegarde créée : {chemin_backup}")


def _action_creer_playlist(chemin: Path, format_detecte: str) -> None:
    if format_detecte != "classic":
        print("\n⚠ La modification n'est pour l'instant possible que sur le format historique DeviceSQL.")
        return
    nom = input("Nom de la nouvelle playlist (ou du dossier) : ").strip()
    if not nom:
        return
    est_dossier = input("Créer un dossier plutôt qu'une playlist ? (o/N) : ").strip().lower() == "o"
    parent_id = input("ID du dossier parent (laisser vide pour la racine) : ").strip() or "0"

    try:
        db = PdbFile(chemin)
        nouvel_id = db.creer_playlist(nom, parent_id=parent_id, is_folder=est_dossier)
        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except (PdbFormatError, ErreurConnexion, OSError) as exc:
        consigner(chemin, "create-playlist", f"name={nom!r} parent_id={parent_id} — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(
        chemin,
        "create-playlist",
        f"name={nom!r} parent_id={parent_id} dossier={est_dossier} -> id={nouvel_id}, backup={chemin_backup}",
        succes=True,
    )
    print(f"\n✔ {'Dossier' if est_dossier else 'Playlist'} « {nom} » créé(e) (id={nouvel_id}).")
    print(f"  Sauvegarde créée : {chemin_backup}")


def _action_suggerer_playlist(chemin: Path, format_detecte: str) -> None:
    if format_detecte != "classic":
        print("\n⚠ La suggestion n'est pour l'instant disponible que sur le format historique DeviceSQL.")
        return
    track_id = input("ID du morceau à trier : ").strip()
    if not track_id:
        return
    try:
        suggestions, nom_suggere = suggerer_playlists_classic(chemin, track_id)
    except ErreurConnexion as exc:
        consigner(chemin, "suggest-playlist", f"track_id={track_id} — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(chemin, "suggest-playlist", f"track_id={track_id} -> {len(suggestions)} suggestion(s)", succes=True)

    if not suggestions:
        if nom_suggere:
            print(f"\nAucune playlist existante ne correspond. Nom suggéré pour une nouvelle playlist : « {nom_suggere} ».")
            reponse = input("Créer cette playlist maintenant ? (o/N) : ").strip().lower()
            if reponse == "o":
                _creer_et_ajouter(chemin, nom_suggere, track_id)
        else:
            print("\nAucune playlist existante ne correspond, et pas assez d'information pour suggérer un nom.")
        return

    print("\nPlaylists suggérées :")
    for i, s in enumerate(suggestions, start=1):
        print(f"  {i}. {s.nom} (score={s.score})")
        for raison in s.raisons:
            print(f"       · {raison}")
    choix = input("\nNuméro de la playlist à utiliser (Entrée pour ne rien faire) : ").strip()
    if not choix:
        return
    try:
        index = int(choix) - 1
        cible = suggestions[index]
    except (ValueError, IndexError):
        print("Choix invalide.")
        return
    confirmation = input(f"Ajouter le morceau {track_id} à « {cible.nom} » ? (o/N) : ").strip().lower()
    if confirmation != "o":
        print("Annulé.")
        return
    try:
        db = PdbFile(chemin)
        entry_index = db.ajouter_morceau(cible.playlist_id, track_id)
        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except (PdbFormatError, ErreurConnexion, OSError) as exc:
        consigner(chemin, "add-track", f"playlist_id={cible.playlist_id} track_id={track_id} (via suggestion) — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(
        chemin,
        "add-track",
        f"playlist_id={cible.playlist_id} track_id={track_id} (via suggestion) -> entry_index={entry_index}, backup={chemin_backup}",
        succes=True,
    )
    print(f"\n✔ Morceau {track_id} ajouté à « {cible.nom} ».")
    print(f"  Sauvegarde créée : {chemin_backup}")


def _creer_et_ajouter(chemin: Path, nom: str, track_id: str) -> None:
    try:
        db = PdbFile(chemin)
        nouvel_id = db.creer_playlist(nom)
        db.ajouter_morceau(nouvel_id, track_id)
        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except (PdbFormatError, ErreurConnexion, OSError) as exc:
        consigner(chemin, "create-playlist", f"name={nom!r} (via suggestion) — {exc}", succes=False)
        print(f"\n⚠ {exc}")
        return
    consigner(
        chemin, "create-playlist", f"name={nom!r} (via suggestion) -> id={nouvel_id}, track_id={track_id}, backup={chemin_backup}", succes=True
    )
    print(f"\n✔ Playlist « {nom} » créée (id={nouvel_id}) et morceau {track_id} ajouté.")
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
            print("5. Créer une playlist (ou un dossier)")
            print("6. Ajouter un morceau à une playlist")
            print("7. Suggérer une playlist pour un morceau (tri semi-automatique)")
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
        elif choix == "5" and ecriture_possible:
            _action_creer_playlist(chemin, format_detecte)
        elif choix == "6" and ecriture_possible:
            _action_ajouter_morceau(chemin, format_detecte)
        elif choix == "7" and ecriture_possible:
            _action_suggerer_playlist(chemin, format_detecte)
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
