from __future__ import annotations

from pathlib import Path

import pytest
from pdb_builder import construire_fichier_pdb, ligne_artist, ligne_track
from rbmanager.pdb_format import TableType

from app.library.rbmanager_adapter import RbManagerAdapter
from app.plan.apply import apply_plan
from app.plan.builder import PlaylistChange, OrganizationPlan
from app.plan.history import HistoryRepo


@pytest.fixture()
def bibliotheque(tmp_path: Path) -> Path:
    tables = {
        TableType.ARTISTS: [ligne_artist(1, "Niska"), ligne_artist(2, "Drake")],
        TableType.TRACKS: [
            ligne_track(100, "Reseaux", artist_id=1),
            ligne_track(101, "Medicament", artist_id=1),
            ligne_track(200, "Hotline Bling", artist_id=2),
        ],
        TableType.PLAYLIST_TREE: [],
        TableType.PLAYLIST_ENTRIES: [],
    }
    return construire_fichier_pdb(tmp_path, tables)


def test_apply_plan_cree_playlists_et_ajoute_morceaux(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    plan = OrganizationPlan(
        changes=[
            PlaylistChange(genre="Rap FR", track_ids=["100", "101"]),
            PlaylistChange(genre="Rap US", track_ids=["200"]),
        ],
        nb_tracks_total=3,
        nb_artists_total=2,
        nb_known_from_db=2,
        nb_researched=0,
    )

    resultat = apply_plan(plan, adapter)

    assert set(resultat.playlists_created) == {"Rap FR", "Rap US"}
    assert resultat.nb_tracks_moved == 3
    assert resultat.backup_path.exists()

    relu = RbManagerAdapter(bibliotheque)
    assert relu.find_playlist_by_name("Rap FR").nb_tracks == 2
    assert relu.find_playlist_by_name("Rap US").nb_tracks == 1


def test_apply_plan_reutilise_playlist_existante(bibliotheque: Path):
    adapter = RbManagerAdapter(bibliotheque)
    adapter.create_playlist("Rap FR")
    adapter.save()

    adapter2 = RbManagerAdapter(bibliotheque)
    plan = OrganizationPlan(changes=[PlaylistChange(genre="Rap FR", track_ids=["100"])], nb_tracks_total=1, nb_artists_total=1, nb_known_from_db=1, nb_researched=0)
    resultat = apply_plan(plan, adapter2)

    assert resultat.playlists_created == []
    assert resultat.playlists_reused == ["Rap FR"]


def test_undo_via_history_et_backup(bibliotheque: Path):
    with HistoryRepo(":memory:") as history:
        adapter = RbManagerAdapter(bibliotheque)
        plan = OrganizationPlan(changes=[PlaylistChange(genre="Rap FR", track_ids=["100"])], nb_tracks_total=1, nb_artists_total=1, nb_known_from_db=1, nb_researched=0)
        resultat = apply_plan(plan, adapter)
        run = history.record_run("lib-1", nb_tracks=1, playlists_created=resultat.playlists_created, playlists_reused=[], backup_path=str(resultat.backup_path))

        assert RbManagerAdapter(bibliotheque).find_playlist_by_name("Rap FR") is not None

        adapter.restore_backup(run.backup_path)
        history.mark_undone(run.id)

        assert RbManagerAdapter(bibliotheque).find_playlist_by_name("Rap FR") is None
        assert history.get(run.id).undone is True


def test_history_list_for_library(bibliotheque: Path):
    with HistoryRepo(":memory:") as history:
        history.record_run("lib-1", 10, ["Rap FR"], [], "/tmp/backup1.pdb")
        history.record_run("lib-1", 20, ["Rap US"], [], "/tmp/backup2.pdb")
        history.record_run("lib-2", 5, ["Techno"], [], "/tmp/backup3.pdb")

        runs = history.list_for_library("lib-1")
        assert len(runs) == 2
        assert runs[0].nb_tracks == 20  # le plus récent en premier
