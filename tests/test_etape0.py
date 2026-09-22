from __future__ import annotations

from pathlib import Path

import pytest

from rbmanager.etape0 import (
    EXIT_BASE_CORROMPUE,
    EXIT_CLE_INTROUVABLE,
    EXIT_OK,
    ErreurConnexion,
    lister_playlists,
    main,
    ouvrir_base,
    resoudre_chemin_export_pdb,
    verifier_structure_cle,
)


def test_resoudre_chemin_avec_usb(tmp_path: Path) -> None:
    chemin = resoudre_chemin_export_pdb(str(tmp_path), None)
    assert chemin == tmp_path / "PIONEER" / "rekordbox" / "export.pdb"


def test_resoudre_chemin_avec_db_path_direct(tmp_path: Path) -> None:
    fichier = tmp_path / "export.pdb"
    fichier.touch()
    chemin = resoudre_chemin_export_pdb(None, str(fichier))
    assert chemin == fichier


def test_verifier_structure_leve_si_absent(tmp_path: Path) -> None:
    with pytest.raises(ErreurConnexion) as exc_info:
        verifier_structure_cle(tmp_path / "inexistant.pdb")
    assert exc_info.value.code_sortie == EXIT_CLE_INTROUVABLE


def test_lister_playlists_construit_la_hierarchie(cle_usb_valide: Path) -> None:
    chemin = resoudre_chemin_export_pdb(str(cle_usb_valide), None)
    db = ouvrir_base(chemin, None)
    try:
        playlists = lister_playlists(db)
    finally:
        db.close()

    assert len(playlists) == 2
    dossier = next(p for p in playlists if p.nom == "Genres")
    assert dossier.type == "dossier"
    assert {e.nom for e in dossier.enfants} == {"Speed Garage", "UK Garage"}
    hard_techno = next(p for p in playlists if p.nom == "Hard Techno")
    assert hard_techno.type == "playlist"


def test_base_corrompue_donne_code_sortie_dedie(cle_usb_base_corrompue: Path) -> None:
    # La classification de l'erreur (base corrompue vs autre) n'a lieu que
    # dans main(), car l'ouverture SQLAlchemy est paresseuse : l'échec réel
    # de déchiffrement ne survient qu'à la première requête (voir ouvrir_base).
    code = main(["--usb", str(cle_usb_base_corrompue), "--format", "json"])
    assert code == EXIT_BASE_CORROMPUE


def test_main_json_succes(cle_usb_valide: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--usb", str(cle_usb_valide), "--format", "json"])
    assert code == EXIT_OK
    sortie = capsys.readouterr().out
    assert '"succes": true' in sortie
    assert "Speed Garage" in sortie


def test_main_cle_introuvable(tmp_path: Path) -> None:
    code = main(["--usb", str(tmp_path), "--format", "json"])
    assert code == EXIT_CLE_INTROUVABLE
