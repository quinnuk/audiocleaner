"""
Top-level orchestration: recursively find MKV files, probe them (in
parallel, since probing is I/O + small subprocess calls), then process
them one at a time (remuxing is disk-heavy, so we do this sequentially
for safety and to avoid disk thrashing).

This module is UI-agnostic; it reports progress via plain callbacks so it
can be driven from a QThread (see worker.py) or a CLI/test harness.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import CACHE_FILENAME, MKV_EXTENSIONS
from .probe import ProbeCache, probe_file
from .processor import process_file, ProcessResult, ProcessingCancelled
from .history import ProcessingHistory


@dataclass
class ScanSummary:
    total_scanned: int = 0
    cleaned: int = 0
    skipped_single_track: int = 0
    no_english: int = 0
    unknown_codec: int = 0
    errors: int = 0
    total_removed_tracks: int = 0
    total_removed_subtitle_tracks: int = 0
    total_bytes_saved: int = 0
    elapsed_seconds: float = 0.0
    results: list = field(default_factory=list)  # list[ProcessResult]


def find_mkv_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in MKV_EXTENSIONS
    )


def run_pipeline(
    root: Path,
    on_progress: Optional[Callable[..., None]] = None,
    on_file_done: Optional[Callable[[ProcessResult], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    probe_workers: int = 4,
    keep_commentary: bool = False,
    subtitle_filter_enabled: bool = False,
    subtitle_languages: Optional[set] = None,
    preview_only: bool = False,
    max_safety_mode: bool = False,
    persistent_backup: bool = False,
    history: Optional[ProcessingHistory] = None,
    preferred_languages: Optional[set] = None,
) -> ScanSummary:
    """
    on_progress(files_done, files_total, current_filename, phase, file_pct)
    is called repeatedly during both the scan and process phases. file_pct
    is -1 except while a remux is actively in progress, where it's the
    current file's own 0-100 completion (from mkvmerge's --gui-mode
    output) -- this is what lets a single large file show real progress
    instead of appearing frozen for however long its remux takes.
    on_file_done(ProcessResult) is called once per file after processing.
    should_cancel() lets the caller request an early stop -- checked
    between files, AND polled every ~0.5s during an in-progress remux, so
    cancelling actually interrupts a slow/stuck file instead of waiting
    for it to finish or time out.
    """
    start = time.time()
    summary = ScanSummary()

    files = find_mkv_files(root)
    total = len(files)
    if total == 0:
        summary.elapsed_seconds = time.time() - start
        return summary

    cache = ProbeCache(root / CACHE_FILENAME)

    owns_history = history is None
    if owns_history:
        try:
            history = ProcessingHistory()
        except Exception:
            history = None  # history is a convenience feature; never block a scan on it

    # --- Phase 1: parallel metadata scan (populates cache) ---
    probed = 0
    with ThreadPoolExecutor(max_workers=probe_workers) as pool:
        futures = {pool.submit(probe_file, f, cache): f for f in files}
        for future in as_completed(futures):
            f = futures[future]
            probed += 1
            if on_progress:
                on_progress(probed, total, f.name, "scanning", -1)
            try:
                future.result()
            except Exception:
                pass  # errors surface again during processing phase
    cache.save()

    # --- Phase 2: sequential processing (remux is disk I/O heavy) ---
    for i, f in enumerate(files, start=1):
        if should_cancel and should_cancel():
            break
        if on_progress:
            on_progress(i, total, f.name, "processing", -1)

        def _on_remux_progress(pct, _i=i, _f=f):
            if on_progress:
                on_progress(_i, total, _f.name, "processing", int(pct * 100))

        try:
            result = process_file(
                f, cache=cache,
                keep_commentary=keep_commentary,
                subtitle_filter_enabled=subtitle_filter_enabled,
                subtitle_languages=subtitle_languages,
                preview_only=preview_only,
                max_safety_mode=max_safety_mode,
                persistent_backup=persistent_backup,
                preferred_languages=preferred_languages,
                on_remux_progress=_on_remux_progress if on_progress else None,
                should_cancel=should_cancel,
            )
        except ProcessingCancelled:
            break  # the in-progress file's temp output was already cleaned up

        summary.results.append(result)
        summary.total_scanned += 1

        if result.status == "cleaned":
            summary.cleaned += 1
            summary.total_removed_tracks += result.removed_track_count
            summary.total_removed_subtitle_tracks += result.removed_subtitle_count
            summary.total_bytes_saved += result.bytes_saved
        elif result.status == "skipped_single_track":
            summary.skipped_single_track += 1
        elif result.status == "no_english":
            summary.no_english += 1
        elif result.status == "unknown_codec":
            summary.unknown_codec += 1
        elif result.status == "error":
            summary.errors += 1

        if on_file_done:
            on_file_done(result)

        if history is not None:
            try:
                history.record(str(root), result)
            except Exception:
                pass  # never let a history-logging failure abort the run

    cache.save()
    if owns_history and history is not None:
        history.close()
    summary.elapsed_seconds = time.time() - start
    return summary


def scan_subtitle_languages(
    root: Path,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
    probe_workers: int = 4,
) -> set:
    """
    Quick pass to discover which subtitle languages exist across every MKV
    file under root, used to populate the GUI's language checklist. Shares
    the same probe cache as run_pipeline, so this is near-instant on a
    library that's already been scanned before.
    """
    files = find_mkv_files(root)
    if not files:
        return set()

    cache = ProbeCache(root / CACHE_FILENAME)
    langs: set = set()
    done = 0
    with ThreadPoolExecutor(max_workers=probe_workers) as pool:
        futures = {pool.submit(probe_file, f, cache): f for f in files}
        for future in as_completed(futures):
            f = futures[future]
            done += 1
            if on_progress:
                on_progress(done, len(files), f.name, "scanning")
            try:
                result = future.result()
            except Exception:
                continue
            for t in result.subtitle_tracks:
                langs.add(t.language.lower())
    cache.save()
    return langs
