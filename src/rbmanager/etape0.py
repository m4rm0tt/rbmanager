"""
Étape 0 — Script de validation de connexion à la base Rekordbox.

Ce script se connecte à la base binaire `export.pdb` exportée par Rekordbox
sur une clé USB, puis liste les playlists existantes (avec leur hiérarchie
de dossiers). Il ne modifie jamais la base : c'est un outil de diagnostic,
pas encore le gestionnaire complet.

Objectif : valider que rbmanager sait bien lire la base produite par la
version de Rekordbox et le matériel de l'utilisateur, et que la structure
de la clé USB est correcte, avant de construire le reste du logiciel
(v1 : création/suppression/modification de playlists).

Rekordbox exporte en réalité DEUX formats différents sous le nom
`export.pdb`, selon le matériel ciblé :
- Le format historique DeviceSQL (non chiffré), utilisé par les CDJ/XDJ
  classiques (dont la XDJ-RX3). Lu ici via `rbmanager.pdb_format`, un
  parseur maison basé sur la spécification communautaire (voir ce module
  pour les références) — `pyrekordbox` ne le supporte pas du tout.
- Le format récent "Device Library Plus" (SQLite chiffré SQLCipher), pour
  du matériel plus récent (OPUS-QUAD, OMNIS-DUO, XDJ-AZ). Lu via
  `pyrekordbox`.

Ce script détecte automatiquement lequel des deux formats est présent.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Codes de sortie distincts pour que Cowork (ou tout script appelant)
# puisse distinguer les causes d'échec sans avoir à parser le texte.
EXIT_OK = 0
EXIT_CLE_INTROUVABLE = 2       # Pas de export.pdb trouvé à l'emplacement attendu
EXIT_BASE_CORROMPUE = 3        # export.pdb trouvé mais illisible / déchiffrement impossible
EXIT_REKORDBOX_OUVERT = 4      # Rekordbox tourne encore et verrouille la base
EXIT_FORMAT_NON_SUPPORTE = 5   # Opération d'écriture demandée sur un format qui ne la supporte pas encore
EXIT_PLAYLIST_INTROUVABLE = 6
EXIT_OPERATION_NON_SUPPORTEE = 7  # Ex : suppression d'un dossier
EXIT_ASSOCIATION_INTROUVABLE = 8  # Le morceau n'était pas dans la playlist visée
EXIT_ERREUR_INCONNUE = 10      # Tout autre échec imprévu


class ErreurConnexion(Exception):
    """Erreur "métier" avec un code de sortie associé, affichée proprement à l'utilisateur."""

    def __init__(self, message: str, code_sortie: int):
        super().__init__(message)
        self.code_sortie = code_sortie


@dataclass
class InfoPlaylist:
    id: str
    nom: str
    type: str  # "playlist" | "dossier" | "playlist_intelligente"
    nb_morceaux: int
    enfants: list["InfoPlaylist"] = field(default_factory=list)

    def vers_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nom": self.nom,
            "type": self.type,
            "nb_morceaux": self.nb_morceaux,
            "enfants": [e.vers_dict() for e in self.enfants],
        }


@dataclass
class InfoMorceau:
    id: str
    titre: str

    def vers_dict(self) -> dict[str, Any]:
        return {"id": self.id, "titre": self.titre}


def resoudre_chemin_export_pdb(usb: str | None, db_path: str | None) -> Path:
    """Détermine le chemin vers export.pdb à partir d'une racine de clé USB ou d'un chemin direct."""
    if db_path:
        chemin = Path(db_path)
        if chemin.is_dir():
            chemin = chemin / "export.pdb"
        return chemin

    if usb:
        racine = Path(usb)
        # Rekordbox place toujours la base ici, quel que soit l'OS.
        candidat = racine / "PIONEER" / "rekordbox" / "export.pdb"
        if candidat.exists():
            return candidat
        # Certaines clés utilisent une casse différente (FAT32/exFAT ne sont
        # pas sensibles à la casse sous Windows, mais peuvent l'être une fois
        # montées sous Linux) : on cherche une correspondance insensible à la casse.
        if racine.is_dir():
            for p in racine.rglob("export.pdb"):
                if "pioneer" in str(p.parent).lower() and "rekordbox" in str(p.parent).lower():
                    return p
        return candidat

    raise ErreurConnexion(
        "Aucun chemin fourni : indique --usb <racine de la clé> ou --db-path <chemin vers export.pdb>.",
        EXIT_CLE_INTROUVABLE,
    )


def verifier_structure_cle(chemin_export_pdb: Path) -> None:
    """Vérifie que le fichier export.pdb existe bien à l'emplacement attendu."""
    if not chemin_export_pdb.exists():
        raise ErreurConnexion(
            (
                f"Fichier introuvable : {chemin_export_pdb}\n"
                "La clé ne semble pas avoir de structure Rekordbox valide "
                "(dossier attendu : PIONEER/rekordbox/export.pdb).\n"
                "Vérifie que la clé a bien été exportée depuis Rekordbox "
                "(menu Fichier > Exporter la collection vers un périphérique)."
            ),
            EXIT_CLE_INTROUVABLE,
        )
    if not chemin_export_pdb.is_file():
        raise ErreurConnexion(
            f"Le chemin trouvé n'est pas un fichier : {chemin_export_pdb}",
            EXIT_CLE_INTROUVABLE,
        )


def detecter_format(chemin_export_pdb: Path) -> str:
    """Détecte si export.pdb est au format historique DeviceSQL ou SQLCipher.

    Le format historique commence toujours par quatre octets nuls (voir
    `rbmanager.pdb_format`). Une base SQLCipher, elle, est chiffrée dès le
    premier octet : ses 4 premiers octets ont une probabilité négligeable
    d'être tous nuls (1 chance sur 2^32).
    """
    with open(chemin_export_pdb, "rb") as f:
        debut = f.read(4)
    if debut == b"\x00\x00\x00\x00":
        return "classic"
    return "sqlcipher"


def lister_playlists_classic(chemin_export_pdb: Path) -> list[InfoPlaylist]:
    """Liste les playlists d'un export.pdb au format historique DeviceSQL."""
    from rbmanager.pdb_format import PdbFile, PdbFormatError

    try:
        db = PdbFile(chemin_export_pdb)
        tree_rows = db.playlist_tree_rows()
        entry_rows = db.playlist_entry_rows()
    except PdbFormatError as exc:
        raise ErreurConnexion(str(exc), EXIT_BASE_CORROMPUE) from exc
    except (struct.error, IndexError, UnicodeDecodeError) as exc:
        raise ErreurConnexion(
            f"Le fichier ne respecte pas la structure attendue du format export.pdb : {exc}",
            EXIT_BASE_CORROMPUE,
        ) from exc

    nb_morceaux_par_playlist: dict[str, int] = {}
    for entry in entry_rows:
        nb_morceaux_par_playlist[entry.playlist_id] = nb_morceaux_par_playlist.get(entry.playlist_id, 0) + 1

    ids_connus = {row.id for row in tree_rows}
    noeuds: dict[str, InfoPlaylist] = {
        row.id: InfoPlaylist(
            id=row.id,
            nom=row.name or "(sans nom)",
            type="dossier" if row.is_folder else "playlist",
            nb_morceaux=0 if row.is_folder else nb_morceaux_par_playlist.get(row.id, 0),
        )
        for row in tree_rows
    }

    racine: list[InfoPlaylist] = []
    for row in tree_rows:
        noeud = noeuds[row.id]
        if row.parent_id in ids_connus and row.parent_id != row.id:
            noeuds[row.parent_id].enfants.append(noeud)
        else:
            # parent_id == "0" (ou parent absent) : playlist/dossier de premier niveau.
            racine.append(noeud)

    return racine


def contenu_playlist_classic(chemin_export_pdb: Path, playlist_id: str) -> list[InfoMorceau]:
    """Liste les morceaux (dans l'ordre) d'une playlist, format historique DeviceSQL."""
    from rbmanager.pdb_format import PdbFile, PdbFormatError

    try:
        db = PdbFile(chemin_export_pdb)
        tree_rows = db.playlist_tree_rows()
        if not any(r.id == playlist_id for r in tree_rows):
            raise ErreurConnexion(f"Playlist introuvable (id={playlist_id}).", EXIT_PLAYLIST_INTROUVABLE)
        entries = sorted(
            (e for e in db.playlist_entry_rows() if e.playlist_id == playlist_id),
            key=lambda e: e.entry_index,
        )
        titres = db.track_titles()
    except PdbFormatError as exc:
        raise ErreurConnexion(str(exc), EXIT_BASE_CORROMPUE) from exc
    except (struct.error, IndexError, UnicodeDecodeError) as exc:
        raise ErreurConnexion(
            f"Le fichier ne respecte pas la structure attendue du format export.pdb : {exc}",
            EXIT_BASE_CORROMPUE,
        ) from exc

    return [InfoMorceau(id=e.track_id, titre=titres.get(e.track_id) or "(titre inconnu)") for e in entries]


def contenu_playlist_sqlcipher(db: Any, playlist_id: str) -> list[InfoMorceau]:
    """Liste les morceaux d'une playlist, format SQLCipher (Device Library Plus)."""
    ligne = db.get_playlist(ID=playlist_id)
    if ligne is None:
        raise ErreurConnexion(f"Playlist introuvable (id={playlist_id}).", EXIT_PLAYLIST_INTROUVABLE)

    morceaux = []
    for song in ligne.Songs:
        titre = song.Content.Title if song.Content is not None else None
        morceaux.append(InfoMorceau(id=song.ContentID, titre=titre or "(titre inconnu)"))
    return morceaux


def classifier_exception(exc: Exception) -> ErreurConnexion:
    """Traduit une exception bas niveau (sqlcipher/sqlalchemy) en erreur claire pour l'utilisateur."""
    # SQLAlchemy inclut souvent la requête SQL complète dans str(exc) : on ne
    # garde que la première ligne (le message d'origine du pilote) pour rester lisible.
    premiere_ligne = str(exc).strip().splitlines()[0] if str(exc).strip() else str(exc)
    message = premiere_ligne.lower()
    if "file is not a database" in message or "unable to open" in message or "cipher" in message or "hmac" in message:
        return ErreurConnexion(
            (
                "Impossible de déchiffrer/lire export.pdb : le fichier est peut-être "
                "corrompu, incomplet (copie interrompue) ou provient d'une version "
                "de Rekordbox non encore supportée par pyrekordbox.\n"
                f"Détail technique : {premiere_ligne}"
            ),
            EXIT_BASE_CORROMPUE,
        )
    return ErreurConnexion(f"Erreur inattendue lors de la lecture de la base : {premiere_ligne}", EXIT_ERREUR_INCONNUE)


def ouvrir_base(chemin_export_pdb: Path, cle: str | None) -> Any:
    """Ouvre la base export.pdb via pyrekordbox et renvoie l'objet Rekordbox6Database.

    pyrekordbox gère seul le déchiffrement (SQLCipher) : la clé de
    déchiffrement standard est intégrée à la bibliothèque et déduite
    automatiquement. On ne fournit --key que si l'utilisateur a une
    version de Rekordbox pour laquelle la clé automatique ne fonctionne
    pas (voir la doc de pyrekordbox : `pyrekordbox download-key`).

    Attention : l'ouverture de la session SQLAlchemy est paresseuse — une
    base corrompue ou mal déchiffrée ne lève une erreur qu'à la première
    requête, pas ici. C'est pourquoi `main()` englobe aussi le premier
    appel à `lister_playlists` dans la même gestion d'erreurs.
    """
    try:
        from pyrekordbox import Rekordbox6Database
        from pyrekordbox.utils import get_rekordbox_pid
    except ImportError as exc:  # pragma: no cover - ne devrait pas arriver dans l'exécutable packagé
        raise ErreurConnexion(
            f"La bibliothèque pyrekordbox n'est pas disponible : {exc}",
            EXIT_ERREUR_INCONNUE,
        ) from exc

    # Rekordbox verrouille sa base tant qu'il tourne : mieux vaut prévenir
    # clairement plutôt que de laisser sqlcipher échouer avec un message obscur.
    try:
        pid = get_rekordbox_pid()
    except Exception:
        pid = None
    if pid:
        raise ErreurConnexion(
            "Rekordbox est actuellement lancé sur cette machine. "
            "Ferme Rekordbox avant toute lecture ou modification de la clé USB.",
            EXIT_REKORDBOX_OUVERT,
        )

    kwargs: dict[str, Any] = {"path": str(chemin_export_pdb)}
    if cle:
        kwargs["key"] = cle

    try:
        return Rekordbox6Database(**kwargs)
    except FileNotFoundError as exc:
        raise ErreurConnexion(str(exc), EXIT_CLE_INTROUVABLE) from exc
    except Exception as exc:  # noqa: BLE001 - on traduit toute erreur bas niveau en message clair
        raise classifier_exception(exc) from exc


def lister_playlists(db: Any) -> list[InfoPlaylist]:
    """Construit l'arbre des playlists (dossiers inclus) à partir de la base ouverte."""
    lignes = list(db.get_playlist())
    par_id = {ligne.ID: ligne for ligne in lignes}

    def type_de(ligne: Any) -> str:
        if ligne.is_folder:
            return "dossier"
        if ligne.is_smart_playlist:
            return "playlist_intelligente"
        return "playlist"

    def nb_morceaux(ligne: Any) -> int:
        if ligne.is_folder:
            return 0
        try:
            return len(list(ligne.Songs))
        except Exception:
            return 0

    noeuds: dict[str, InfoPlaylist] = {
        ligne.ID: InfoPlaylist(id=ligne.ID, nom=ligne.Name or "(sans nom)", type=type_de(ligne), nb_morceaux=nb_morceaux(ligne))
        for ligne in lignes
    }

    racine: list[InfoPlaylist] = []
    for ligne in lignes:
        noeud = noeuds[ligne.ID]
        parent_id = ligne.ParentID
        if parent_id and parent_id in par_id and parent_id != ligne.ID:
            noeuds[parent_id].enfants.append(noeud)
        else:
            # ParentID == "root" (ou parent absent de la base) : playlist de premier niveau.
            racine.append(noeud)

    return racine


def afficher_texte(playlists: list[InfoPlaylist], niveau: int = 0) -> None:
    for pl in playlists:
        indent = "  " * niveau
        if pl.type == "dossier":
            print(f"{indent}📁 {pl.nom}/")
        else:
            etiquette = " [intelligente]" if pl.type == "playlist_intelligente" else ""
            print(f"{indent}🎵 {pl.nom}{etiquette} ({pl.nb_morceaux} morceau(x))")
        if pl.enfants:
            afficher_texte(pl.enfants, niveau + 1)


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(
        prog="rbmanager-etape0",
        description="Étape 0 : teste la connexion à export.pdb et liste les playlists existantes.",
    )
    groupe = parseur.add_mutually_exclusive_group(required=True)
    groupe.add_argument("--usb", help="Chemin racine de la clé USB (ex: E:\\ ou /media/cle-usb).")
    groupe.add_argument("--db-path", help="Chemin direct vers export.pdb (ou son dossier parent).")
    parseur.add_argument("--key", default=None, help="Clé SQLCipher à utiliser si la clé automatique échoue.")
    parseur.add_argument("--format", choices=["text", "json"], default="text", help="Format de sortie.")
    return parseur


def main(argv: list[str] | None = None) -> int:
    args = construire_parseur().parse_args(argv)
    db = None
    format_detecte = None
    try:
        chemin = resoudre_chemin_export_pdb(args.usb, args.db_path)
        verifier_structure_cle(chemin)
        format_detecte = detecter_format(chemin)

        if format_detecte == "classic":
            playlists = lister_playlists_classic(chemin)
        else:
            db = ouvrir_base(chemin, args.key)
            try:
                playlists = lister_playlists(db)
            except Exception as exc:  # noqa: BLE001 - la vraie erreur de déchiffrement surgit ici (session paresseuse)
                raise classifier_exception(exc) from exc
    except ErreurConnexion as exc:
        if args.format == "json":
            print(json.dumps({"succes": False, "erreur": str(exc), "code_sortie": exc.code_sortie}, ensure_ascii=False, indent=2))
        else:
            print(f"ERREUR : {exc}", file=sys.stderr)
        return exc.code_sortie
    finally:
        if db is not None:
            db.close()

    if args.format == "json":
        resultat = {
            "succes": True,
            "chemin_export_pdb": str(chemin),
            "format_detecte": format_detecte,
            "nb_playlists_racine": len(playlists),
            "playlists": [p.vers_dict() for p in playlists],
        }
        print(json.dumps(resultat, ensure_ascii=False, indent=2))
    else:
        print(f"Connexion réussie : {chemin}")
        print(f"Format détecté : {'historique DeviceSQL (CDJ/XDJ classiques)' if format_detecte == 'classic' else 'SQLCipher (Device Library Plus)'}")
        print()
        if not playlists:
            print("Aucune playlist trouvée sur cette clé.")
        else:
            afficher_texte(playlists)

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
