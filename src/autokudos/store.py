"""SQLite: idempotencja kudos, limity dzienne i historia uruchomień."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from autokudos.models import Activity, RunStats

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kudos (
    activity_id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    athlete_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'unverified')),
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kudos_status_created
    ON kudos (status, created_at);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    dry_run INTEGER NOT NULL,
    found INTEGER NOT NULL DEFAULT 0,
    candidates INTEGER NOT NULL DEFAULT 0,
    sent INTEGER NOT NULL DEFAULT 0,
    would_send INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    aborted TEXT,
    error TEXT
);
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "error" not in columns:
            self._conn.execute("ALTER TABLE runs ADD COLUMN error TEXT")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def record_kudos(
        self,
        activity: Activity,
        status: str,
        *,
        error: str | None = None,
        when: datetime | None = None,
    ) -> None:
        if status not in {"sent", "failed", "unverified"}:
            raise ValueError(f"Nieznany status kudos: {status}")
        timestamp = _iso(when or _utc_now())
        self._conn.execute(
            """
            INSERT INTO kudos (
                activity_id, athlete_id, athlete_name, status, error,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                athlete_id = excluded.athlete_id,
                athlete_name = excluded.athlete_name,
                status = CASE
                    WHEN kudos.status = 'sent' THEN 'sent'
                    ELSE excluded.status
                END,
                error = CASE
                    WHEN kudos.status = 'sent' THEN kudos.error
                    ELSE excluded.error
                END,
                updated_at = excluded.updated_at
            """,
            (
                activity.id,
                activity.athlete_id,
                activity.athlete_name,
                status,
                error,
                timestamp,
                timestamp,
            ),
        )
        self._conn.commit()

    def has_sent(self, activity_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM kudos WHERE activity_id = ? AND status = 'sent'",
            (str(activity_id),),
        ).fetchone()
        return row is not None

    def get_kudos(self, activity_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM kudos WHERE activity_id = ?",
            (str(activity_id),),
        ).fetchone()
        return dict(row) if row is not None else None

    def count_sent_between(self, start: datetime, end: datetime) -> int:
        """Liczy wysłane kudos (także niepotwierdzone) w przedziale UTC."""

        row = self._conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM kudos
            WHERE status IN ('sent', 'unverified')
              AND created_at >= ? AND created_at < ?
            """,
            (_iso(start), _iso(end)),
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    def count_by_status(self, status: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM kudos WHERE status = ?",
            (status,),
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    def start_run(self, *, started_at: datetime, dry_run: bool) -> int:
        cursor = self._conn.execute(
            "INSERT INTO runs (started_at, dry_run) VALUES (?, ?)",
            (_iso(started_at), 1 if dry_run else 0),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        stats: RunStats,
        *,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE runs SET
                finished_at = ?,
                found = ?,
                candidates = ?,
                sent = ?,
                would_send = ?,
                skipped = ?,
                errors = ?,
                aborted = ?,
                error = ?
            WHERE id = ?
            """,
            (
                _iso(finished_at or _utc_now()),
                stats.found,
                stats.candidates,
                stats.sent,
                stats.would_send,
                stats.skipped,
                stats.errors,
                stats.aborted,
                error,
                run_id,
            ),
        )
        self._conn.commit()

    def last_run(self) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row is not None else None
