"""
Artist Classification Database — SQLite, un seul fichier partagé par
tout le produit (base de connaissance qui grandit avec chaque
utilisateur, voir ARCHITECTURE.md §3 et PROJECT_CONTEXT.md §6-7-27).

Index unique sur `normalized_artist_name` : c'est la colonne du chemin
chaud (Track -> Artist -> Genre). `batch_lookup` fait UNE seule requête
`WHERE normalized_artist_name IN (...)` pour toute une bibliothèque,
jamais une requête par artiste.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artist_classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_name TEXT NOT NULL,
    normalized_artist_name TEXT NOT NULL,
    primary_genre TEXT NOT NULL,
    genres TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_artist_classifications_normalized
    ON artist_classifications(normalized_artist_name);
CREATE INDEX IF NOT EXISTS ix_artist_classifications_genre
    ON artist_classifications(primary_genre);
"""


@dataclass
class ClassificationRecord:
    artist_name: str
    normalized_artist_name: str
    primary_genre: str
    genres: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source: str = "unknown"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "artist_name": self.artist_name,
            "normalized_artist_name": self.normalized_artist_name,
            "primary_genre": self.primary_genre,
            "genres": self.genres,
            "confidence": self.confidence,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row: sqlite3.Row) -> ClassificationRecord:
    return ClassificationRecord(
        artist_name=row["artist_name"],
        normalized_artist_name=row["normalized_artist_name"],
        primary_genre=row["primary_genre"],
        genres=json.loads(row["genres"]),
        confidence=row["confidence"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ArtistClassificationRepo:
    """Un seul fichier SQLite pour toute l'installation (pas par bibliothèque
    ni par utilisateur) : c'est ce qui permet à la base de connaissance de
    profiter à toutes les futures bibliothèques importées."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = db_path
        # check_same_thread=False : FastAPI exécute les endpoints synchrones
        # dans un threadpool (voir starlette.concurrency.run_in_threadpool),
        # alors que ce dépôt est un singleton créé une fois au démarrage
        # (voir app/state.py). Un seul thread accède à la connexion à la
        # fois côté appelant (pas de connexion partagée entre requêtes
        # concurrentes réellement simultanées dans ce MVP mono-process).
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL" if str(db_path) != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Compteur de requêtes SELECT exposé pour les tests de performance
        # (vérifier qu'un lookup de N artistes fait 1 requête, pas N).
        self.select_query_count = 0

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ArtistClassificationRepo":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def batch_lookup(self, normalized_names: list[str]) -> dict[str, ClassificationRecord]:
        """Renvoie {normalized_artist_name: ClassificationRecord} pour les
        artistes déjà connus parmi `normalized_names`, en UNE requête."""
        noms_uniques = [n for n in dict.fromkeys(normalized_names) if n]
        if not noms_uniques:
            return {}
        placeholders = ",".join("?" for _ in noms_uniques)
        self.select_query_count += 1
        rows = self._conn.execute(
            f"SELECT * FROM artist_classifications WHERE normalized_artist_name IN ({placeholders})",
            noms_uniques,
        ).fetchall()
        return {row["normalized_artist_name"]: _row_to_record(row) for row in rows}

    def get(self, normalized_artist_name: str) -> ClassificationRecord | None:
        self.select_query_count += 1
        row = self._conn.execute(
            "SELECT * FROM artist_classifications WHERE normalized_artist_name = ?",
            (normalized_artist_name,),
        ).fetchone()
        return _row_to_record(row) if row else None

    def upsert(
        self,
        artist_name: str,
        normalized_artist_name: str,
        primary_genre: str,
        genres: list[str] | None = None,
        confidence: float = 0.5,
        source: str = "unknown",
    ) -> ClassificationRecord:
        """Crée ou met à jour la classification d'un artiste. Idempotent :
        rappeler avec le même artiste met juste `updated_at` à jour."""
        genres = genres if genres is not None else [primary_genre]
        existant = self.get(normalized_artist_name)
        now = _now()
        if existant is None:
            self._conn.execute(
                "INSERT INTO artist_classifications "
                "(artist_name, normalized_artist_name, primary_genre, genres, confidence, source, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (artist_name, normalized_artist_name, primary_genre, json.dumps(genres), confidence, source, now, now),
            )
        else:
            self._conn.execute(
                "UPDATE artist_classifications SET artist_name=?, primary_genre=?, genres=?, confidence=?, source=?, updated_at=? "
                "WHERE normalized_artist_name=?",
                (artist_name, primary_genre, json.dumps(genres), confidence, source, now, normalized_artist_name),
            )
        self._conn.commit()
        return self.get(normalized_artist_name)  # type: ignore[return-value]

    def upsert_many(self, records: list[ClassificationRecord]) -> None:
        """Écrit plusieurs classifications en une seule transaction (pour
        persister d'un coup les résultats de recherche d'artistes inconnus)."""
        now = _now()
        for r in records:
            existant = self.get(r.normalized_artist_name)
            if existant is None:
                self._conn.execute(
                    "INSERT INTO artist_classifications "
                    "(artist_name, normalized_artist_name, primary_genre, genres, confidence, source, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (r.artist_name, r.normalized_artist_name, r.primary_genre, json.dumps(r.genres or [r.primary_genre]), r.confidence, r.source, now, now),
                )
            else:
                self._conn.execute(
                    "UPDATE artist_classifications SET artist_name=?, primary_genre=?, genres=?, confidence=?, source=?, updated_at=? "
                    "WHERE normalized_artist_name=?",
                    (r.artist_name, r.primary_genre, json.dumps(r.genres or [r.primary_genre]), r.confidence, r.source, now, r.normalized_artist_name),
                )
        self._conn.commit()

    def list_all(self, search: str | None = None, genre: str | None = None) -> list[ClassificationRecord]:
        query = "SELECT * FROM artist_classifications WHERE 1=1"
        params: list = []
        if search:
            query += " AND (artist_name LIKE ? OR normalized_artist_name LIKE ?)"
            like = f"%{search}%"
            params += [like, like]
        if genre:
            query += " AND primary_genre = ?"
            params.append(genre)
        query += " ORDER BY artist_name COLLATE NOCASE"
        self.select_query_count += 1
        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_record(r) for r in rows]

    def delete(self, normalized_artist_name: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM artist_classifications WHERE normalized_artist_name = ?", (normalized_artist_name,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def count(self) -> int:
        self.select_query_count += 1
        return self._conn.execute("SELECT COUNT(*) AS n FROM artist_classifications").fetchone()["n"]
