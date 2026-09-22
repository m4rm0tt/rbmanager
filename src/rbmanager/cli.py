"""
CLI unifiée de rbmanager — début de la v1 (au-delà de l'étape 0).

Deux façons de piloter cet exécutable :
- Mode non-interactif (pour Cowork / un agent) : `rbmanager <commande> --usb ... [--format json]`.
  Toutes les commandes sont documentées dans docs/cli-reference.md.
- Mode interactif (pour un humain) : lancer `rbmanager` sans aucun argument
  (ou double-cliquer sur l'exécutable) ouvre un menu en texte. Le menu
  appelle exactement les mêmes fonctions que le mode non-interactif : le
  comportement est garanti identique dans les deux modes.

Les commandes d'écriture (delete-playlist, remove-track) ne fonctionnent
pour l'instant que sur le format historique DeviceSQL (CDJ/XDJ classiques,
dont la XDJ-RX3) : le format SQLCipher ("Device Library Plus") n'a pas
encore d'équivalent d'écriture ici. Chaque écriture fait systématiquement,
dans cet ordre : (1) une sauvegarde horodatée dans backups/, (2) la
modification en mémoire, (3) l'écriture sur le disque si tout s'est bien
passé. Les opérations disponibles ne font que basculer des bits de
présence déjà alloués (aucune réorganisation du tas), pour limiter le
risque de corruption tant que l'ajout de nouvelles lignes n'a pas été
implémenté ni testé aussi largement.
"""

from __future__ import annotations

import argparse
import json
import sys

from rbmanager.backup import sauvegarder
from rbmanager.etape0 import (
    EXIT_ASSOCIATION_INTROUVABLE,
    EXIT_BASE_CORROMPUE,
    EXIT_ERREUR_INCONNUE,
    EXIT_FORMAT_NON_SUPPORTE,
    EXIT_OK,
    EXIT_OPERATION_NON_SUPPORTEE,
    EXIT_PLAYLIST_INTROUVABLE,
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


def commande_list_playlists(args) -> int:
    db = None
    try:
        chemin = resoudre_chemin_export_pdb(args.usb, args.db_path)
        verifier_structure_cle(chemin)
        format_detecte = detecter_format(chemin)
        if format_detecte == "classic":
            playlists = lister_playlists_classic(chemin)
        else:
            db = ouvrir_base(chemin, None)
            try:
                playlists = lister_playlists(db)
            except Exception as exc:  # noqa: BLE001
                raise classifier_exception(exc) from exc
    except ErreurConnexion as exc:
        return _sortie(False, args, erreur=str(exc), code_sortie=exc.code_sortie)
    finally:
        if db is not None:
            db.close()

    if args.format == "json":
        return _sortie(
            True,
            args,
            chemin_export_pdb=str(chemin),
            format_detecte=format_detecte,
            playlists=[p.vers_dict() for p in playlists],
        )
    print(f"Format détecté : {format_detecte}")
    if not playlists:
        print("Aucune playlist trouvée sur cette clé.")
    else:
        afficher_texte(playlists)
    return EXIT_OK


def commande_show_playlist(args) -> int:
    db = None
    try:
        chemin = resoudre_chemin_export_pdb(args.usb, args.db_path)
        verifier_structure_cle(chemin)
        format_detecte = detecter_format(chemin)
        if format_detecte == "classic":
            morceaux = contenu_playlist_classic(chemin, args.playlist_id)
        else:
            db = ouvrir_base(chemin, None)
            try:
                morceaux = contenu_playlist_sqlcipher(db, args.playlist_id)
            except ErreurConnexion:
                raise
            except Exception as exc:  # noqa: BLE001
                raise classifier_exception(exc) from exc
    except ErreurConnexion as exc:
        return _sortie(False, args, erreur=str(exc), code_sortie=exc.code_sortie)
    finally:
        if db is not None:
            db.close()

    if args.format == "json":
        return _sortie(
            True,
            args,
            playlist_id=args.playlist_id,
            nb_morceaux=len(morceaux),
            morceaux=[m.vers_dict() for m in morceaux],
        )
    if not morceaux:
        print("Cette playlist ne contient aucun morceau.")
    else:
        for i, m in enumerate(morceaux, start=1):
            print(f"{i:>3}. {m.titre}  (id={m.id})")
    return EXIT_OK


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
    parseur = argparse.ArgumentParser(
        prog="rbmanager",
        description="Gestionnaire de playlists Rekordbox pour clé USB. Sans argument : menu interactif.",
    )
    sous_parseurs = parseur.add_subparsers(dest="commande")

    def ajouter_arguments_communs(p: argparse.ArgumentParser) -> None:
        groupe = p.add_mutually_exclusive_group(required=True)
        groupe.add_argument("--usb", help="Chemin racine de la clé USB.")
        groupe.add_argument("--db-path", help="Chemin direct vers export.pdb.")
        p.add_argument("--format", choices=["text", "json"], default="text")

    p_list = sous_parseurs.add_parser("list-playlists", help="Liste les playlists (et dossiers) de la clé.")
    ajouter_arguments_communs(p_list)
    p_list.set_defaults(func=commande_list_playlists)

    p_show = sous_parseurs.add_parser("show-playlist", help="Affiche le contenu (morceaux) d'une playlist.")
    p_show.add_argument("--playlist-id", required=True)
    ajouter_arguments_communs(p_show)
    p_show.set_defaults(func=commande_show_playlist)

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
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        # Aucun argument : on lance le menu interactif plutôt que d'exiger
        # une sous-commande, pour qu'un humain puisse juste double-cliquer
        # sur l'exécutable (voir docstring du module).
        from rbmanager.interactive import lancer_menu_interactif

        return lancer_menu_interactif()

    args = construire_parseur().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
