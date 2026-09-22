from __future__ import annotations

import pytest

from app.classification.db_repo import ArtistClassificationRepo
from app.normalization import normalize_artist_name


@pytest.fixture()
def repo():
    with ArtistClassificationRepo(":memory:") as r:
        yield r


def test_upsert_puis_get(repo: ArtistClassificationRepo):
    repo.upsert("Niska", normalize_artist_name("Niska"), "Rap FR", confidence=0.98, source="web_search")
    record = repo.get(normalize_artist_name("niska"))
    assert record is not None
    assert record.primary_genre == "Rap FR"
    assert record.confidence == 0.98


def test_get_artiste_inconnu_renvoie_none(repo: ArtistClassificationRepo):
    assert repo.get("artiste-totalement-inconnu") is None


def test_upsert_idempotent_met_a_jour(repo: ArtistClassificationRepo):
    repo.upsert("Niska", "niska", "Rap FR", confidence=0.9, source="web_search")
    repo.upsert("Niska", "niska", "Afro", confidence=0.99, source="manual")
    record = repo.get("niska")
    assert record.primary_genre == "Afro"
    assert record.source == "manual"
    assert repo.count() == 1  # pas de doublon


def test_batch_lookup_une_seule_requete_pour_plusieurs_artistes(repo: ArtistClassificationRepo):
    repo.upsert("Niska", "niska", "Rap FR")
    repo.upsert("Gazo", "gazo", "Rap FR")
    repo.upsert("Drake", "drake", "Rap US")

    avant = repo.select_query_count
    resultats = repo.batch_lookup(["niska", "gazo", "drake", "artiste-inconnu"])
    apres = repo.select_query_count

    assert apres - avant == 1, "le batch lookup doit faire EXACTEMENT une requête, quel que soit le nombre d'artistes"
    assert set(resultats.keys()) == {"niska", "gazo", "drake"}
    assert resultats["niska"].primary_genre == "Rap FR"


def test_batch_lookup_liste_vide(repo: ArtistClassificationRepo):
    assert repo.batch_lookup([]) == {}


def test_batch_lookup_deduplique_les_entrees(repo: ArtistClassificationRepo):
    repo.upsert("Niska", "niska", "Rap FR")
    resultats = repo.batch_lookup(["niska", "niska", "niska"])
    assert resultats == {"niska": repo.get("niska")}


def test_list_all_filtre_par_recherche_et_genre(repo: ArtistClassificationRepo):
    repo.upsert("Niska", "niska", "Rap FR")
    repo.upsert("Gazo", "gazo", "Rap FR")
    repo.upsert("Drake", "drake", "Rap US")

    assert {r.artist_name for r in repo.list_all(genre="Rap FR")} == {"Niska", "Gazo"}
    assert {r.artist_name for r in repo.list_all(search="rak")} == {"Drake"}


def test_delete(repo: ArtistClassificationRepo):
    repo.upsert("Niska", "niska", "Rap FR")
    assert repo.delete("niska") is True
    assert repo.get("niska") is None
    assert repo.delete("niska") is False


def test_upsert_many_une_seule_transaction(repo: ArtistClassificationRepo):
    from app.classification.db_repo import ClassificationRecord

    records = [
        ClassificationRecord("Niska", "niska", "Rap FR", ["Rap FR"], 0.9, "web_search"),
        ClassificationRecord("Gazo", "gazo", "Rap FR", ["Rap FR"], 0.9, "web_search"),
    ]
    repo.upsert_many(records)
    assert repo.count() == 2
