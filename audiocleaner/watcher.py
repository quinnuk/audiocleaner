"""
Continuous watch mode: polls a folder tree for new or still-copying MKV
files and only hands a file to the processor once its size has stopped
changing for `settle_seconds`.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import MKV_EXTENSIONS
from .probe import ProbeCache
from .processor import process_file, ProcessResult
from .history import ProcessingHistory


@dataclass(frozen=True)
class _FileIdentity:
    size: int
    mtime_ns: int


@dataclass
class _Sighting:
    identity: _FileIdentity
    last_size_change: float


class WatchState:
    """Tracks per-file stability and successful processing across polls."""

    def __init__(self):
        self._sightings: dict[str, _Sighting] = {}
        # Store the identity, not merely the path. If a processed file is
        # deleted and a different file is later moved into the same path, it
        # must be eligible for processing again.
        self._processed: dict[str, _FileIdentity] = {}

    def _identity(self, path: Path) -> Optional[_FileIdentity]:
        try:
            stat = path.stat()
        except OSError:
            return None
        return _FileIdentity(size=stat.st_size, mtime_ns=stat.st_mtime_ns)

    def observe(self, path: Path) -> Optional[_Sighting]:
        identity = self._identity(path)
        if identity is None:
            return None
        key = str(path)
        now = time.time()
        prev = self._sightings.get(key)
        if prev is None or prev.identity != identity:
            sighting = _Sighting(identity=identity, last_size_change=now)
        else:
            sighting = prev
        self._sightings[key] = sighting
        return sighting

    def is_settled(self, path: Path, settle_seconds: int) -> bool:
        sighting = self._sightings.get(str(path))
        if sighting is None:
            return False
        return (time.time() - sighting.last_size_change) >= settle_seconds

    def mark_processed(self, path: Path):
        identity = self._identity(path)
        if identity is not None:
            self._processed[str(path)] = identity
        self._sightings.pop(str(path), None)

    def mark_retryable(self, path: Path):
        """Leave the current file eligible for a later poll after an error."""
        self._processed.pop(str(path), None)
        # Keep the sighting so a transient error does not force another full
        # settle interval when the file itself has not changed.

    def already_processed(self, path: Path) -> bool:
        identity = self._identity(path)
        if identity is None:
            return False
        return self._processed.get(str(path)) == identity


def watch_iteration(
    root: Path,
    state: WatchState,
    cache: ProbeCache,
    settle_seconds: int,
    keep_commentary: bool = False,
    subtitle_filter_enabled: bool = False,
    subtitle_languages: Optional[set] = None,
    max_safety_mode: bool = False,
    persistent_backup: bool = False,
    history: Optional[ProcessingHistory] = None,
) -> list[ProcessResult]:
    """One polling pass over the folder tree."""
    results = []
    for path in sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in MKV_EXTENSIONS
    ):
        if state.already_processed(path):
            continue

        sighting = state.observe(path)
        if sighting is None:
            continue

        if not state.is_settled(path, settle_seconds):
            continue

        result = process_file(
            path, cache=cache,
            keep_commentary=keep_commentary,
            subtitle_filter_enabled=subtitle_filter_enabled,
            subtitle_languages=subtitle_languages,
            max_safety_mode=max_safety_mode,
            persistent_backup=persistent_backup,
        )
        results.append(result)

        # Only successful/non-error outcomes become processed. A transient
        # MediaInfo/mkvmerge failure, a locked file, or a temporary I/O issue
        # should be retried instead of being permanently suppressed for the
        # rest of the watch session.
        if result.status == "error":
            state.mark_retryable(path)
        else:
            state.mark_processed(path)

        if history is not None:
            try:
                history.record(str(root), result)
            except Exception:
                pass

    return results
