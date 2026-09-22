"""
Test d'intégration bout-en-bout de l'API FastAPI, sur une bibliothèque
synthétique : upload -> analyze (preview) -> apply (confirmation) ->
history -> undo -> chat -> artists. Isole ses données dans un dossier
temporaire dédié (voir la variable d'environnement ci-dessous, LUE UNE
SEULE FOIS à l'import de app.state — donc fixée avant tout import de
app.main/app.state, y compris transitif).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["DJ_ORGANIZER_DATA_DIR"] = tempfile.mkdtemp(prefix="dj_organizer_test_")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pdb_builder import construire_fichier_pdb, ligne_artist, ligne_track  # noqa: E402
from rbmanager.pdb_format import TableType  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture()
def bibliotheque_bytes(tmp_path: Path) -> bytes:
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
    chemin = construire_fichier_pdb(tmp_path, tables)
    return chemin.read_bytes()


def _upload(bibliotheque_bytes: bytes) -> str:
    resp = client.post("/api/library/upload", files={"file": ("export.pdb", bibliotheque_bytes, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    return resp.json()["library_id"]


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_upload_renvoie_nb_tracks(bibliotheque_bytes: bytes):
    resp = client.post("/api/library/upload", files={"file": ("export.pdb", bibliotheque_bytes, "application/octet-stream")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nb_tracks"] == 3
    assert "library_id" in body


def test_analyze_renvoie_un_plan_previsualisable(bibliotheque_bytes: bytes):
    library_id = _upload(bibliotheque_bytes)
    resp = client.post(f"/api/library/{library_id}/analyze")
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["summary"]["nb_tracks"] == 3
    genres = {c["name"] for c in plan["changes"]}
    assert "Rap FR" in genres
    assert "Rap US" in genres


def test_apply_cree_reellement_les_playlists(bibliotheque_bytes: bytes):
    library_id = _upload(bibliotheque_bytes)
    client.post(f"/api/library/{library_id}/analyze")
    resp = client.post(f"/api/library/{library_id}/apply")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nb_tracks_moved"] == 3
    assert "Rap FR" in body["playlists_created"]

    playlists = client.get(f"/api/library/{library_id}/playlists").json()["playlists"]
    noms = {p["name"] for p in playlists}
    assert "Rap FR" in noms and "Rap US" in noms


def test_download_apres_apply(bibliotheque_bytes: bytes):
    library_id = _upload(bibliotheque_bytes)
    client.post(f"/api/library/{library_id}/apply")
    resp = client.get(f"/api/library/{library_id}/download")
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_history_et_undo(bibliotheque_bytes: bytes):
    library_id = _upload(bibliotheque_bytes)
    client.post(f"/api/library/{library_id}/apply")

    history = client.get(f"/api/library/{library_id}/history").json()["runs"]
    assert len(history) == 1
    run_id = history[0]["id"]

    playlists_avant = {p["name"] for p in client.get(f"/api/library/{library_id}/playlists").json()["playlists"]}
    assert "Rap FR" in playlists_avant

    resp = client.post(f"/api/library/{library_id}/history/{run_id}/undo")
    assert resp.status_code == 200

    playlists_apres = {p["name"] for p in client.get(f"/api/library/{library_id}/playlists").json()["playlists"]}
    assert "Rap FR" not in playlists_apres

    # Un second undo du même run doit être refusé (déjà annulé).
    resp2 = client.post(f"/api/library/{library_id}/history/{run_id}/undo")
    assert resp2.status_code == 409


def test_chat_modifie_le_plan_sans_toucher_a_la_bibliotheque(bibliotheque_bytes: bytes):
    library_id = _upload(bibliotheque_bytes)

    resp = client.post(f"/api/library/{library_id}/chat", json={"message": "Mets Niska dans Afro."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["understood"] is True
    genres = {c["name"] for c in body["plan"]["changes"]}
    assert "Afro" in genres

    # La bibliothèque n'a PAS été modifiée par le chat (aucune playlist créée).
    playlists = client.get(f"/api/library/{library_id}/playlists").json()["playlists"]
    assert playlists == []


def test_artists_list_et_update(bibliotheque_bytes: bytes):
    library_id = _upload(bibliotheque_bytes)
    client.post(f"/api/library/{library_id}/analyze")  # peuple la DB d'artistes

    resp = client.get("/api/artists", params={"search": "niska"})
    assert resp.status_code == 200
    artistes = resp.json()["artists"]
    assert any(a["artist_name"] == "Niska" for a in artistes)

    normalized = next(a["normalized_artist_name"] for a in artistes if a["artist_name"] == "Niska")
    resp2 = client.patch(f"/api/artists/{normalized}", json={"primary_genre": "Afro", "confidence": 1.0})
    assert resp2.status_code == 200
    assert resp2.json()["primary_genre"] == "Afro"
    assert resp2.json()["source"] == "manual"


def test_artist_correct_endpoint_global(bibliotheque_bytes: bytes):
    resp = client.post(
        "/api/artists/correct",
        json={"artist_name": "Niska", "new_genre": "Afro", "remember_globally": True},
    )
    assert resp.status_code == 200
    assert resp.json()["scope"] == "global"

    artistes = client.get("/api/artists", params={"search": "niska"}).json()["artists"]
    assert any(a["primary_genre"] == "Afro" for a in artistes)


def test_upload_inexistant_renvoie_404():
    assert client.post("/api/library/inexistant/analyze").status_code == 404
    assert client.get("/api/library/inexistant/download").status_code == 404
