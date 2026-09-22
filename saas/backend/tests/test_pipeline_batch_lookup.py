"""
Tests du pipeline de classification (app.classification.pipeline) — en
particulier la contrainte n°1 du produit : le nombre de recherches
externes doit être proportionnel au nombre d'ARTISTES uniques inconnus,
jamais au nombre de morceaux (voir PROJECT_CONTEXT.md §6/§25/§26).
"""

from __future__ import annotations

import pytest

from app.classification.db_repo import ArtistClassificationRepo
from app.classification.pipeline import TrackArtistInput, classify_library
from app.classification.research import CountingResearcher, SeedListResearcher


@pytest.fixture()
def repo():
    with ArtistClassificationRepo(":memory:") as r:
        yield r


def test_classification_de_base_niska(repo: ArtistClassificationRepo):
    researcher = CountingResearcher(SeedListResearcher())
    tracks = [
        TrackArtistInput("1", "Niska", "Réseaux"),
        TrackArtistInput("2", "Niska", "Médicament"),
        TrackArtistInput("3", "Niska", "Commando"),
        TrackArtistInput("4", "Niska", "Mr Sal"),
        TrackArtistInput("5", "Niska", "Coco"),
    ]
    resultat = classify_library(tracks, repo, researcher)

    assert all(t.primary_genre == "Rap FR" for t in resultat.tracks)
    assert researcher.call_count == 1, "5 morceaux du même artiste ne doivent déclencher qu'UNE recherche"
    assert resultat.stats.nb_tracks == 5
    assert resultat.stats.nb_unique_artists == 1
    assert resultat.stats.nb_researched == 1


def test_artiste_deja_connu_ne_declenche_aucune_recherche(repo: ArtistClassificationRepo):
    repo.upsert("Niska", "niska", "Rap FR", confidence=0.98, source="web_search")
    researcher = CountingResearcher(SeedListResearcher())
    tracks = [TrackArtistInput(str(i), "Niska", f"Track {i}") for i in range(10)]

    resultat = classify_library(tracks, repo, researcher)

    assert researcher.call_count == 0, "un artiste déjà en DB ne doit jamais déclencher de recherche externe"
    assert resultat.stats.nb_known_from_db == 1
    assert all(t.primary_genre == "Rap FR" and t.source == "web_search" for t in resultat.tracks)


def test_1000_tracks_100_artistes_80_connus_20_inconnus(repo: ArtistClassificationRepo):
    """Le test de performance demandé par le cahier des charges (§25) :
    1000 tracks, 100 artistes uniques, 80 déjà en DB, 20 inconnus ->
    recherches externes attendues ~20, PAS 1000."""
    artistes = [f"Artiste {i:03d}" for i in range(100)]
    for nom in artistes[:80]:
        repo.upsert(nom, nom.lower(), "Other", confidence=0.5, source="seed_test")

    tracks = [TrackArtistInput(str(i), artistes[i % 100], f"Track {i}") for i in range(1000)]

    researcher = CountingResearcher(SeedListResearcher())
    resultat = classify_library(tracks, repo, researcher)

    assert resultat.stats.nb_tracks == 1000
    assert resultat.stats.nb_unique_artists == 100
    assert resultat.stats.nb_known_from_db == 80
    assert resultat.stats.nb_researched == 20
    assert researcher.call_count == 20, f"attendu 20 appels de recherche, obtenu {researcher.call_count}"
    assert researcher.call_count < resultat.stats.nb_tracks, "jamais une recherche par morceau"


def test_deuxieme_organisation_plus_rapide_car_db_deja_remplie(repo: ArtistClassificationRepo):
    """Simule le critère de réussite §26 : une deuxième bibliothèque
    contenant les mêmes artistes ne déclenche plus aucune recherche."""
    tracks_a = [TrackArtistInput("1", "Niska", "Réseaux"), TrackArtistInput("2", "Gazo", "Bandana")]
    researcher = CountingResearcher(SeedListResearcher())
    classify_library(tracks_a, repo, researcher)
    assert researcher.call_count == 2

    tracks_b = [TrackArtistInput("10", "Niska", "Commando"), TrackArtistInput("11", "Gazo", "Drill FR")]
    classify_library(tracks_b, repo, researcher)
    assert researcher.call_count == 2, "les mêmes artistes dans une nouvelle bibliothèque ne doivent plus être recherchés"


def test_collaboration_utilise_le_genre_de_l_artiste_principal(repo: ArtistClassificationRepo):
    researcher = CountingResearcher(SeedListResearcher())
    tracks = [TrackArtistInput("1", "Niska feat. Drake", "Collab")]
    resultat = classify_library(tracks, repo, researcher)

    assert resultat.tracks[0].primary_artist == "Niska"
    assert resultat.tracks[0].primary_genre == "Rap FR"
    assert resultat.tracks[0].all_artists == ["Niska", "Drake"]
    assert researcher.call_count == 2, "Niska ET Drake sont chacun recherchés une fois (base multi-artiste alimentée)"
    # Drake doit maintenant aussi être en DB pour de futurs morceaux où il est artiste principal.
    assert repo.get("drake") is not None


def test_morceau_sans_artiste(repo: ArtistClassificationRepo):
    researcher = CountingResearcher(SeedListResearcher())
    tracks = [TrackArtistInput("1", "", "Sans metadonnee")]
    resultat = classify_library(tracks, repo, researcher)

    assert resultat.tracks[0].primary_genre == "Other"
    assert resultat.stats.nb_tracks_without_artist == 1
    assert researcher.call_count == 0
