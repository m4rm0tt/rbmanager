"""Historique des organisations + undo (voir PROJECT_CONTEXT.md §20)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS organization_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    nb_tracks INTEGER NOT NULL,
    playlists_created TEXT NOT NULL,
    playlists_reused TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    undone INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class OrganizationRunRecord:
    id: int
    library_id: str
    created_at: str
    nb_tracks: int
    playlists_created: list[str]
    playlists_reused: list[str]
    backup_path: str
    undone: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "library_id": self.library_id,
            "created_at": self.created_at,
            "nb_tracks": self.nb_tracks,
            "playlists_created": self.playlists_created,
            "playlists_reused": self.playlists_reused,
            "backup_path": self.backup_path,
            "undone": self.undone,
        }


def _row_to_record(row: sqlite3.Row) -> OrganizationRunRecord:
    return OrganizationRunRecord(
        id=row["id"],
        library_id=row["library_id"],
        created_at=row["created_at"],
        nb_tracks=row["nb_tracks"],
        playlists_created=json.loads(row["playlists_created"]),
        playlists_reused=json.loads(row["playlists_reused"]),
        backup_path=row["backup_path"],
        undone=bool(row["undone"]),
    )


class HistoryRepo:
    def __init__(self, db_path: str | Path = ":memory:"):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)  # voir la note dans db_repo.py
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "HistoryRepo":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def record_run(
        self,
        library_id: str,
        nb_tracks: int,
        playlists_created: list[str],
        playlists_reused: list[str],
        backup_path: str,
    ) -> OrganizationRunRecord:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO organization_runs "
            "(library_id, created_at, nb_tracks, playlists_created, playlists_reused, backup_path, undone) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (library_id, now, nb_tracks, json.dumps(playlists_created), json.dumps(playlists_reused), backup_path),
        )
        self._conn.commit()
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, run_id: int) -> OrganizationRunRecord | None:
        row = self._conn.execute("SELECT * FROM organization_runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_record(row) if row else None

    def list_for_library(self, library_id: str) -> list[OrganizationRunRecord]:
        rows = self._conn.execute(
            "SELECT * FROM organization_runs WHERE library_id = ? ORDER BY id DESC", (library_id,)
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def mark_undone(self, run_id: int) -> None:
        self._conn.execute("UPDATE organization_runs SET undone = 1 WHERE id = ?", (run_id,))
        self._conn.commit()
