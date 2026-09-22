from __future__ import annotations

from app.normalization import normalize_artist_name


def test_normalise_casse_et_espaces():
    assert normalize_artist_name("Niska") == normalize_artist_name("niska") == normalize_artist_name("NISKA")
    assert normalize_artist_name("  Niska  ") == normalize_artist_name("Niska")


def test_normalise_accents():
    assert normalize_artist_name("Ömer Faruk Bostan") == normalize_artist_name("Omer Faruk Bostan")
    assert normalize_artist_name("Beéle") == normalize_artist_name("Beele")


def test_normalise_espaces_multiples():
    assert normalize_artist_name("Niska   Officiel") == "niska officiel"


def test_nettoie_suffixe_feat_residuel():
    assert normalize_artist_name("Niska feat.") == normalize_artist_name("Niska")
    assert normalize_artist_name("Niska ft.") == normalize_artist_name("Niska")


def test_artistes_differents_ne_sont_jamais_fusionnes():
    """Pas de fuzzy-matching : deux artistes différents qui se ressemblent
    doivent rester distincts (contrainte explicite du cahier des charges)."""
    assert normalize_artist_name("Niska") != normalize_artist_name("Niskaa")
    assert normalize_artist_name("Drake") != normalize_artist_name("Drakeo")


def test_chaine_vide():
    assert normalize_artist_name("") == ""
    assert normalize_artist_name("   ") == ""
