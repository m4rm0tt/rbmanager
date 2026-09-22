from __future__ import annotations

from app.classification.db_repo import ArtistClassificationRepo
from app.classification.pipeline import TrackArtistInput, classify_library
from app.classification.research import CountingResearcher, SeedListResearcher
from app.plan.builder import build_plan
from app.plan.config import GenreConfig


def _classify(tracks):
    with ArtistClassificationRepo(":memory:") as repo:
        return classify_library(tracks, repo, CountingResearcher(SeedListResearcher()))


def test_plan_regroupe_par_genre():
    tracks = [
        TrackArtistInput("1", "Niska", "Réseaux"),
        TrackArtistInput("2", "Gazo", "Bandana"),
        TrackArtistInput("3", "Drake", "Hotline Bling"),
    ]
    resultat = _classify(tracks)
    plan = build_plan(resultat.tracks, GenreConfig(), resultat.stats)

    genres = {c.genre: c.track_ids for c in plan.changes}
    assert genres["Rap FR"] == ["1", "2"]
    assert genres["Rap US"] == ["3"]
    assert plan.nb_tracks_total == 3
    assert plan.nb_researched == 3


def test_plan_marque_les_playlists_existantes():
    tracks = [TrackArtistInput("1", "Niska", "Réseaux")]
    resultat = _classify(tracks)
    plan = build_plan(resultat.tracks, GenreConfig(), resultat.stats, existing_playlist_names={"Rap FR"})
    assert plan.changes[0].already_exists is True


def test_plan_applique_redirection_de_genre():
    tracks = [TrackArtistInput("1", "Niska", "Réseaux")]
    resultat = _classify(tracks)
    config = GenreConfig()
    config.redirect_genre("Rap FR", "Francophone")
    plan = build_plan(resultat.tracks, config, resultat.stats)
    assert [c.genre for c in plan.changes] == ["Francophone"]


def test_plan_applique_override_artiste():
    tracks = [TrackArtistInput("1", "Niska", "Réseaux")]
    resultat = _classify(tracks)
    config = GenreConfig()
    config.override_artist("Niska", "Afro")
    plan = build_plan(resultat.tracks, config, resultat.stats)
    assert [c.genre for c in plan.changes] == ["Afro"]


def test_plan_to_dict_structure():
    tracks = [TrackArtistInput("1", "Niska", "Réseaux")]
    resultat = _classify(tracks)
    plan = build_plan(resultat.tracks, GenreConfig(), resultat.stats)
    d = plan.to_dict()
    assert d["summary"]["nb_tracks"] == 1
    assert d["changes"][0]["action"] == "create_playlist"
    assert d["changes"][0]["track_ids"] == ["1"]
