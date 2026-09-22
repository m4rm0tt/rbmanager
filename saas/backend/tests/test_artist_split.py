from __future__ import annotations

from app.artist_split import artiste_principal, split_artists


def test_pas_de_multi_artistes():
    assert split_artists("Niska") == ["Niska"]


def test_feat_point():
    assert split_artists("Niska feat. Booba") == ["Niska", "Booba"]


def test_featuring():
    assert split_artists("Niska featuring Booba") == ["Niska", "Booba"]


def test_ft():
    assert split_artists("Niska ft. Booba") == ["Niska", "Booba"]


def test_virgule():
    assert split_artists("Romeo Santos, Prince Royce") == ["Romeo Santos", "Prince Royce"]


def test_virgule_multiple():
    assert split_artists("Edith Piaf, Siks, QQUN") == ["Edith Piaf", "Siks", "QQUN"]


def test_esperluette_avec_espaces():
    assert split_artists("Niska & Booba") == ["Niska", "Booba"]


def test_esperluette_sans_espaces_ne_casse_pas_le_nom_de_duo():
    """W&W est un nom de duo à part entière : ne doit PAS être scindé."""
    assert split_artists("W&W") == ["W&W"]


def test_combinaison_virgule_et_esperluette():
    assert split_artists("Tiagz, Fuerza Regida & El Alfa") == ["Tiagz", "Fuerza Regida", "El Alfa"]


def test_x_minuscule():
    assert split_artists("Skrillex x Diplo") == ["Skrillex", "Diplo"]


def test_deduplique_en_preservant_ordre():
    assert split_artists("Niska feat. Niska") == ["Niska"]


def test_champ_vide():
    assert split_artists("") == []
    assert split_artists("   ") == []


def test_artiste_principal_est_le_premier():
    assert artiste_principal("Niska feat. Booba") == "Niska"
    assert artiste_principal("") is None


def test_donnee_reelle_bibliotheque_utilisateur():
    """Cas réels observés dans la base Rekordbox de test (511 artistes)."""
    assert split_artists("Kybba & Limitless Ft. Leftside") == ["Kybba", "Limitless", "Leftside"]
    assert split_artists("W&W, Dimitri Vegas & Like Mike, Marnik") == [
        "W&W",
        "Dimitri Vegas",
        "Like Mike",
        "Marnik",
    ]
