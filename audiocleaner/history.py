"""
Persistent processing history (spec sec 23/25): a small SQLite database
recording what happened to every file AudioCleaner has looked at, across
every run and every watched folder, so the app can show a history view
("what did you do to Dune.mkv last Tuesday") independent of any single
scan session.

This is deliberately separate from probe.ProbeCache (which is a per-folder
cache keyed on size+mtime, used purely to skip re-probing unchanged files)
-- history is an append-only log, kept centrally so a single view covers
every library.
"""
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import APP_NAME, SCANNER_VERSION, RULES_VERSION

HISTORY_SCHEMA_VERSION = 1


def default_history_db_path() -> Path:
    """Central, per-user location -- independent of any watched folder, so
    history survives folder reorganisation and covers every library from
    one place."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".local" / "share"
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.db"


@dataclass
class HistoryEntry:
    id: int
    timestamp: float
    folder: str
    path: str
    file_size: int
    status: str
    kept_codec: Optional[str]
    removed_track_count: int
    removed_subtitle_count: int
    bytes_saved: int
    message: str
    preview: bool
    scanner_version: str
    rules_version: str
    schema_version: int = HISTORY_SCHEMA_VERSION


class ProcessingHistory:
    """Not shared across threads -- each worker thread should create its
    own instance (cheap: just opens a small local sqlite file)."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else default_history_db_path()
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                folder TEXT NOT NULL,
                path TEXT NOT NULL,
                file_size INTEGER,
                status TEXT NOT NULL,
                kept_codec TEXT,
                removed_track_count INTEGER DEFAULT 0,
                removed_subtitle_count INTEGER DEFAULT 0,
                bytes_saved INTEGER DEFAULT 0,
                message TEXT,
                preview INTEGER DEFAULT 0,
                scanner_version TEXT,
                rules_version TEXT,
                schema_version INTEGER DEFAULT 1
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_history_path ON history(path)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_history_timestamp ON history(timestamp)")
        self._conn.commit()

    def record(self, folder: str, result) -> None:
        """result is a processor.ProcessResult. Preview-mode results are
        recorded too (marked preview=1) so a preview run is visible in
        history as "what would happen", distinct from an actual clean."""
        file_size = 0
        try:
            p = Path(result.path)
            if p.exists():
                file_size = p.stat().st_size
        except OSError:
            pass

        self._conn.execute(
            """INSERT INTO history
               (timestamp, folder, path, file_size, status, kept_codec,
                removed_track_count, removed_subtitle_count, bytes_saved,
                message, preview, scanner_version, rules_version, schema_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(), str(folder), result.path, file_size, result.status,
                result.kept_codec, result.removed_track_count, result.removed_subtitle_count,
                result.bytes_saved, result.message, 1 if result.preview else 0,
                SCANNER_VERSION, RULES_VERSION, HISTORY_SCHEMA_VERSION,
            ),
        )
        self._conn.commit()

    def recent(self, limit: int = 200, status_filter: Optional[str] = None) -> list:
        """Most recent entries first. status_filter, if given, restricts to
        one status (e.g. 'error') -- used by the GUI's history filter."""
        query = "SELECT * FROM history"
        params: list = []
        if status_filter:
            query += " WHERE status = ?"
            params.append(status_filter)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM history LIMIT 0").description]
        return [HistoryEntry(**dict(zip(cols, row))) for row in rows]

    def search(self, term: str, limit: int = 500, status_filter: Optional[str] = None) -> list:
        """Entries whose path contains `term` (case-insensitive substring
        match), most recent first -- backs the History dialog's search box,
        so "what did AudioCleaner do to Dune.mkv last week?" doesn't
        require typing the exact full path."""
        query = "SELECT * FROM history WHERE path LIKE ? COLLATE NOCASE"
        params: list = [f"%{term}%"]
        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        cols = [d[0] for d in self._conn.execute("SELECT * FROM history LIMIT 0").description]
        return [HistoryEntry(**dict(zip(cols, row))) for row in rows]

    def library_totals(self) -> dict:
        """Aggregate across all history -- backs the Library Report (sec 27).
        Only counts non-preview, successfully cleaned entries towards space
        recovered, since preview runs never touched disk."""
        row = self._conn.execute(
            """SELECT
                 COUNT(DISTINCT path) as files_seen,
                 SUM(CASE WHEN status='cleaned' AND preview=0 THEN 1 ELSE 0 END) as files_cleaned,
                 SUM(CASE WHEN status='cleaned' AND preview=0 THEN removed_track_count ELSE 0 END) as tracks_removed,
                 SUM(CASE WHEN status='cleaned' AND preview=0 THEN bytes_saved ELSE 0 END) as bytes_saved
               FROM history"""
        ).fetchone()
        return {
            "files_seen": row[0] or 0,
            "files_cleaned": row[1] or 0,
            "tracks_removed": row[2] or 0,
            "bytes_saved": row[3] or 0,
        }

    def close(self):
        self._conn.close()
