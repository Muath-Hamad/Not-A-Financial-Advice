"""SQLite (WAL) for the console's own state: alert acknowledgements and the
indexer's status. Disposable like the read model (docs/08 §3.1) — the ledger
stays the source of truth; losing this file only forgets acknowledgements.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_state (
  alert_id TEXT PRIMARY KEY,
  status   TEXT NOT NULL CHECK (status IN ('acknowledged', 'resolved')),
  note     TEXT NOT NULL DEFAULT '',
  actor    TEXT NOT NULL,
  at_utc   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS indexer_run (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  at_utc    TEXT NOT NULL,
  ok        INTEGER NOT NULL,
  commit_sha TEXT,
  changed   INTEGER NOT NULL DEFAULT 0,
  error     TEXT
);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def alert_states(self) -> dict[str, sqlite3.Row]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM alert_state").fetchall()
        return {r["alert_id"]: r for r in rows}

    def set_alert(self, alert_id: str, status: str, actor: str, note: str = "") -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO alert_state(alert_id, status, note, actor, at_utc) VALUES (?,?,?,?,?) "
                "ON CONFLICT(alert_id) DO UPDATE SET status=excluded.status, note=excluded.note, "
                "actor=excluded.actor, at_utc=excluded.at_utc",
                (alert_id, status, note, actor, utcnow()))
            self._db.commit()

    def record_index(self, ok: bool, commit: str | None, changed: bool, error: str | None = None) -> None:
        with self._lock:
            self._db.execute("INSERT INTO indexer_run(at_utc, ok, commit_sha, changed, error) VALUES (?,?,?,?,?)",
                             (utcnow(), int(ok), commit, int(changed), error))
            # keep a week of runs at one a minute
            self._db.execute("DELETE FROM indexer_run WHERE id < (SELECT MAX(id) - 10080 FROM indexer_run)")
            self._db.commit()

    def indexer_status(self) -> dict:
        with self._lock:
            last = self._db.execute("SELECT * FROM indexer_run ORDER BY id DESC LIMIT 1").fetchone()
            last_ok = self._db.execute("SELECT * FROM indexer_run WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
            since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat()
            errors = self._db.execute("SELECT COUNT(*), MAX(error) FROM indexer_run WHERE ok=0 AND at_utc>=?", (since,)).fetchone()
        return {
            "last": dict(last) if last else None,
            "last_ok": dict(last_ok) if last_ok else None,
            "errors_24h": errors[0] if errors else 0,
            "last_error": errors[1] if errors else None,
        }
