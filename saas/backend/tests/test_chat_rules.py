from __future__ import annotations

from app.chat.rules import interpret
from app.plan.config import GenreConfig


def test_redirection_genre_baile_funk_vers_latino():
    config = GenreConfig()
    config.add_genre("Baile Funk")
    resultat = interpret("Mets le baile funk dans Latino.", config)

    assert resultat.understood
    assert resultat.action == "redirect_genre"
    assert resultat.config.resolve_genre("N'importe Qui", "Baile Funk") == "Latino"


def test_creation_categorie():
    config = GenreConfig()
    resultat = interpret("Crée une catégorie White Girl Music.", config)

    assert resultat.understood
    assert resultat.action == "create_genre"
    assert "White Girl Music" in resultat.config.genres


def test_separation_deux_genres_annule_une_redirection_precedente():
    config = GenreConfig()
    config.redirect_genre("Tech House", "House")
    resultat = interpret("Je veux séparer House et Tech House.", config)

    assert resultat.understood
    assert resultat.action == "split_genres"
    assert resultat.config.resolve_genre("X", "Tech House") == "Tech House"


def test_override_artiste_car_source_n_est_pas_un_genre_connu():
    config = GenreConfig()
    resultat = interpret("Mets Niska dans Afro.", config)

    assert resultat.understood
    assert resultat.action == "override_artist"
    assert resultat.config.resolve_genre("Niska", "Rap FR") == "Afro"
    # Un autre artiste n'est pas affecté par cet override.
    assert resultat.config.resolve_genre("Gazo", "Rap FR") == "Rap FR"


def test_regle_tout_ce_qui_est_x_doit_aller_dans_y():
    config = GenreConfig()
    config.add_genre("Rap FR")
    resultat = interpret("Tout ce qui est Rap FR doit aller dans Rap FR.", config)
    assert resultat.understood
    assert resultat.config.resolve_genre("X", "Rap FR") == "Rap FR"


def test_message_non_compris():
    config = GenreConfig()
    resultat = interpret("Quelle heure est-il ?", config)
    assert resultat.understood is False
    assert resultat.action == "not_understood"


def test_ne_mute_jamais_la_config_d_origine():
    config = GenreConfig()
    config.add_genre("Rap FR")
    resultat = interpret("Mets Niska dans Afro.", config)
    assert "niska" not in config.artist_overrides
    assert "niska" in resultat.config.artist_overrides
