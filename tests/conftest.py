"""Fixtures pour les tests : construit une fausse base export.pdb chiffrée.

On ne peut pas utiliser une vraie clé USB Rekordbox dans les tests
automatisés, donc on reproduit ici le strict nécessaire du schéma
`djmdPlaylist` (chiffré avec la même clé SQLCipher que celle intégrée à
pyrekordbox) pour valider le comportement de rbmanager sans dépendre d'un
vrai export Rekordbox.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest


def _creer_playlist(id_: str, name: str, attribute: int, parent: str, seq: int):
    from pyrekordbox.db6 import tables

    now = datetime.datetime.now()
    return tables.DjmdPlaylist(
        ID=id_,
        Seq=seq,
        Name=name,
        ImagePath="",
        Attribute=attribute,
        ParentID=parent,
        SmartList="",
        UUID=f"uuid-{id_}",
        rb_data_status=0,
        rb_local_data_status=0,
        rb_local_deleted=0,
        rb_local_synced=0,
        usn=0,
        rb_local_usn=0,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture()
def cle_usb_valide(tmp_path: Path) -> Path:
    """Crée une fausse clé USB avec un export.pdb chiffré contenant quelques playlists."""
    import pyrekordbox.db6.database as dbmod
    from pyrekordbox.db6 import tables
    from pyrekordbox.utils import deobfuscate
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlcipher3 import dbapi2 as sqlcipher

    racine = tmp_path / "cle-usb"
    db_path = racine / "PIONEER" / "rekordbox" / "export.pdb"
    db_path.parent.mkdir(parents=True)

    key = deobfuscate(dbmod.BLOB)
    url = f"sqlite+pysqlcipher://:{key}@/{db_path}?"
    engine = create_engine(url, module=sqlcipher)
    tables.Base.metadata.create_all(engine)

    session = Session(bind=engine)
    dossier = _creer_playlist("1", "Genres", 1, "root", 1)
    pl1 = _creer_playlist("2", "Speed Garage", 0, "1", 1)
    pl2 = _creer_playlist("3", "UK Garage", 0, "1", 2)
    pl3 = _creer_playlist("4", "Hard Techno", 0, "root", 2)
    session.add_all([dossier, pl1, pl2, pl3])
    session.commit()
    session.close()

    return racine


@pytest.fixture()
def cle_usb_base_corrompue(tmp_path: Path) -> Path:
    """Crée une fausse clé USB avec un export.pdb non chiffré (simule une base corrompue)."""
    import sqlite3

    racine = tmp_path / "cle-usb-corrompue"
    db_path = racine / "PIONEER" / "rekordbox" / "export.pdb"
    db_path.parent.mkdir(parents=True)

    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE t (a int)")
    con.commit()
    con.close()

    return racine
