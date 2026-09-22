"""
CLI d'écriture de rbmanager — début de la v1 (au-delà de l'étape 0).

Ces commandes MODIFIENT export.pdb. Elles ne fonctionnent pour l'instant
que sur le format historique DeviceSQL (CDJ/XDJ classiques, dont la
XDJ-RX3) : le format SQLCipher ("Device Library Plus") n'a pas encore
d'équivalent d'écriture ici.

Chaque commande d'écriture fait systématiquement, dans cet ordre :
1. Une sauvegarde horodatée d'export.pdb dans backups/ (jamais désactivable).
2. La modification en mémoire.
3. L'écriture sur le disque, seulement si tout s'est bien passé.

Toutes les opérations d'écriture actuellement disponibles (suppression de
playlist, retrait de morceau) ne font que basculer des bits de présence
déjà alloués : elles ne réorganisent jamais l'espace du fichier. C'est
volontaire, pour limiter le risque de corruption tant que l'ajout de
nouvelles lignes (qui demande d'allouer de l'espace) n'a pas été
implémenté ni testé aussi largement.
"""

from __future__ import annotations

import argparse
import json
import sys

from rbmanager.backup import sauvegarder
from rbmanager.etape0 import (
    EXIT_BASE_CORROMPUE,
    EXIT_ERREUR_INCONNUE,
    EXIT_OK,
    ErreurConnexion,
    detecter_format,
    resoudre_chemin_export_pdb,
    verifier_structure_cle,
)
from rbmanager.pdb_format import PdbFile, PdbFormatError

EXIT_FORMAT_NON_SUPPORTE = 5  # Écriture demandée sur un format qui n'est pas encore pris en charge.
EXIT_PLAYLIST_INTROUVABLE = 6
EXIT_OPERATION_NON_SUPPORTEE = 7  # Ex: suppression d'un dossier.
EXIT_ASSOCIATION_INTROUVABLE = 8  # Le morceau n'était pas dans la playlist visée.


def _ouvrir_pdb_classique(chemin) -> PdbFile:
    """Ouvre le fichier en vérifiant qu'il est bien au format historique (le seul supporté en écriture)."""
    if detecter_format(chemin) != "classic":
        raise ErreurConnexion(
            "L'écriture n'est pour l'instant supportée que pour le format historique DeviceSQL "
            "(CDJ/XDJ classiques). Ce fichier est au format SQLCipher (Device Library Plus).",
            EXIT_FORMAT_NON_SUPPORTE,
        )
    try:
        return PdbFile(chemin)
    except PdbFormatError as exc:
        raise ErreurConnexion(str(exc), EXIT_BASE_CORROMPUE) from exc


def _sortie(succes: bool, args, **champs) -> int:
    donnees = {"succes": succes, **champs}
    if args.format == "json":
        print(json.dumps(donnees, ensure_ascii=False, indent=2))
    else:
        if succes:
            print(champs.get("message", "OK"))
        else:
            print(f"ERREUR : {champs.get('erreur', 'échec inconnu')}", file=sys.stderr)
    return EXIT_OK if succes else champs.get("code_sortie", EXIT_ERREUR_INCONNUE)


def commande_delete_playlist(args) -> int:
    try:
        chemin = resoudre_chemin_export_pdb(args.usb, args.db_path)
        verifier_structure_cle(chemin)
        db = _ouvrir_pdb_classique(chemin)

        try:
            nb_morceaux_retires = db.supprimer_playlist(args.playlist_id)
        except PdbFormatError as exc:
            message = str(exc)
            code = EXIT_OPERATION_NON_SUPPORTEE if "dossiers" in message else EXIT_PLAYLIST_INTROUVABLE
            raise ErreurConnexion(message, code) from exc

        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except ErreurConnexion as exc:
        return _sortie(False, args, erreur=str(exc), code_sortie=exc.code_sortie)

    return _sortie(
        True,
        args,
        message=f"Playlist {args.playlist_id} supprimée ({nb_morceaux_retires} morceau(x) retiré(s) avec elle).",
        playlist_id=args.playlist_id,
        nb_morceaux_retires=nb_morceaux_retires,
        backup=str(chemin_backup),
    )


def commande_remove_track(args) -> int:
    try:
        chemin = resoudre_chemin_export_pdb(args.usb, args.db_path)
        verifier_structure_cle(chemin)
        db = _ouvrir_pdb_classique(chemin)

        trouve = db.retirer_morceau(args.playlist_id, args.track_id)
        if not trouve:
            raise ErreurConnexion(
                f"Le morceau {args.track_id} n'était pas présent dans la playlist {args.playlist_id}.",
                EXIT_ASSOCIATION_INTROUVABLE,
            )

        chemin_backup = sauvegarder(chemin)
        db.enregistrer()
    except ErreurConnexion as exc:
        return _sortie(False, args, erreur=str(exc), code_sortie=exc.code_sortie)

    return _sortie(
        True,
        args,
        message=f"Morceau {args.track_id} retiré de la playlist {args.playlist_id}.",
        playlist_id=args.playlist_id,
        track_id=args.track_id,
        backup=str(chemin_backup),
    )


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(prog="rbmanager", description="Gestionnaire de playlists Rekordbox pour clé USB.")
    sous_parseurs = parseur.add_subparsers(dest="commande", required=True)

    def ajouter_arguments_communs(p: argparse.ArgumentParser) -> None:
        groupe = p.add_mutually_exclusive_group(required=True)
        groupe.add_argument("--usb", help="Chemin racine de la clé USB.")
        groupe.add_argument("--db-path", help="Chemin direct vers export.pdb.")
        p.add_argument("--format", choices=["text", "json"], default="text")

    p_delete = sous_parseurs.add_parser("delete-playlist", help="Supprime une playlist (pas un dossier) et ses morceaux.")
    p_delete.add_argument("--playlist-id", required=True, help="ID de la playlist à supprimer.")
    ajouter_arguments_communs(p_delete)
    p_delete.set_defaults(func=commande_delete_playlist)

    p_remove = sous_parseurs.add_parser("remove-track", help="Retire un morceau d'une playlist.")
    p_remove.add_argument("--playlist-id", required=True)
    p_remove.add_argument("--track-id", required=True)
    ajouter_arguments_communs(p_remove)
    p_remove.set_defaults(func=commande_remove_track)

    return parseur


def main(argv: list[str] | None = None) -> int:
    args = construire_parseur().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
