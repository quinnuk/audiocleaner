"""
Continuous watch mode: polls a folder tree for new or still-copying MKV
files and only hands a file to the processor once its size has stopped
changing for `settle_seconds` -- this is what keeps it from grabbing a
file while Radarr/Sonarr (or any download client) is still moving it into
place.

State is kept in memory only (per watch session); restarting the watcher
re-evaluates the whole tree, which is cheap because probe.ProbeCache
still short-circuits anything that hasn't changed on disk.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import MKV_EXTENSIONS
from .probe import ProbeCache
from .processor import process_file, ProcessResult
from .history import ProcessingHistory


@dataclass
class _Sighting:
    size: int
    last_size_change: float


class WatchState:
    """Tracks per-file size-stability history across polling passes."""

    def __init__(self):
        self._sightings: dict[str, _Sighting] = {}
        self._processed: set[str] = set()

    def observe(self, path: Path) -> Optional[_Sighting]:
        try:
            size = path.stat().st_size
        except OSError:
            return None
        key = str(path)
        now = time.time()
        prev = self._sightings.get(key)
        if prev is None or prev.size != size:
            sighting = _Sighting(size=size, last_size_change=now)
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
        self._processed.add(str(path))
        self._sightings.pop(str(path), None)

    def already_processed(self, path: Path) -> bool:
        return str(path) in self._processed


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
    preferred_languages: Optional[set] = None,
) -> list[ProcessResult]:
    """
    One polling pass over the folder tree. Returns a ProcessResult for
    every file that was stable-and-not-yet-processed this pass (usually
    zero, since most passes find nothing new).
    """
    results = []
    for path in sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in MKV_EXTENSIONS
    ):
        if state.already_processed(path):
            continue

        sighting = state.observe(path)
        if sighting is None:
            continue  # unreadable / vanished mid-poll, try again next pass

        if not state.is_settled(path, settle_seconds):
            continue  # still copying (or just arrived) -- wait

        result = process_file(
            path, cache=cache,
            keep_commentary=keep_commentary,
            subtitle_filter_enabled=subtitle_filter_enabled,
            subtitle_languages=subtitle_languages,
            max_safety_mode=max_safety_mode,
            persistent_backup=persistent_backup,
            preferred_languages=preferred_languages,
        )
        # Mark processed regardless of outcome (including errors) so a
        # broken file doesn't get retried forever on every poll.
        state.mark_processed(path)
        results.append(result)

        if history is not None:
            try:
                history.record(str(root), result)
            except Exception:
                pass  # never let a history-logging failure disrupt watching

    return results
