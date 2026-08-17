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

from .config import (
    CACHE_FILENAME, MKV_EXTENSIONS, is_own_generated_file,
    DEFAULT_REMUX_STALL_TIMEOUT_SECONDS,
)
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
        and not is_own_generated_file(p)
    )


def check_drive_responsiveness(root: Path, warn_threshold_seconds: float = 5.0) -> Optional[str]:
    """
    Quick, cheap check performed once before a batch starts: times how
    long a trivial directory listing on `root` takes. A spun-down
    external/USB drive, or a network share that's gone to sleep, can take
    several seconds -- sometimes much longer -- to respond to its very
    first access after being idle. That delay used to be indistinguishable
    from mkvmerge genuinely being stuck (see the stall-timeout fix in
    processor.py); surfacing it here, before any file processing starts,
    explains it up front instead of silently eating into the first file's
    stall-timeout budget.

    Returns a human-readable heads-up message if `root` was slow to
    respond, or None if it responded promptly. Never raises -- if root is
    inaccessible, the real scan below will report that properly.
    """
    start = time.time()
    try:
        # next(iterdir(), None) -- not just stat() -- is what actually
        # forces a spun-down drive to wake and start responding to reads;
        # stat() on the root itself can be served from a cached directory
        # entry higher up without touching the physical/network volume.
        # Only the first entry is pulled, so this stays cheap even on a
        # huge folder once the drive is actually awake.
        next(root.iterdir(), None)
    except OSError:
        return None  # let the real scan surface this properly
    elapsed = time.time() - start
    if elapsed >= warn_threshold_seconds:
        return (f"{root} took {elapsed:.1f}s to respond to its first read -- looks like a "
                f"spun-down drive or a sleeping network share. This is normal after it's "
                f"been idle; the first file or two may be slower than usual while it "
                f"wakes up properly.")
    return None


def run_pipeline(
    root: Path,
    on_progress: Optional[Callable[..., None]] = None,
    on_file_done: Optional[Callable[[ProcessResult], None]] = None,
    on_notice: Optional[Callable[[str], None]] = None,
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
    only_paths: Optional[list] = None,
    stall_timeout_seconds: int = DEFAULT_REMUX_STALL_TIMEOUT_SECONDS,
) -> ScanSummary:
    """
    on_progress(files_done, files_total, current_filename, phase, file_pct)
    is called repeatedly during both the scan and process phases. file_pct
    is -1 except while a remux is actively in progress, where it's the
    current file's own 0-100 completion (from mkvmerge's --gui-mode
    output) -- this is what lets a single large file show real progress
    instead of appearing frozen for however long its remux takes.
    on_file_done(ProcessResult) is called once per file after processing.
    on_notice(message) is called for informational, non-per-file heads-up
    messages -- currently just a slow-to-respond drive detected before the
    batch starts (see check_drive_responsiveness above).
    should_cancel() lets the caller request an early stop -- checked
    between files, AND polled every ~0.5s during an in-progress remux, so
    cancelling actually interrupts a slow/stuck file instead of waiting
    for it to finish or time out.
    only_paths, if given, restricts processing to exactly these files
    (still under `root`) instead of the usual full recursive scan -- used
    to retry just the files that errored on a previous run without
    re-touching everything else.
    """
    start = time.time()
    summary = ScanSummary()

    if on_notice:
        drive_notice = check_drive_responsiveness(root)
        if drive_notice:
            on_notice(drive_notice)

    if only_paths is not None:
        files = sorted(
            p for p in only_paths
            if p.is_file() and p.suffix.lower() in MKV_EXTENSIONS
            and not is_own_generated_file(p)
        )
    else:
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
                stall_timeout_seconds=stall_timeout_seconds,
            )
        except ProcessingCancelled:
            break  # the in-progress file's temp output was already cleaned up
        except FileNotFoundError as e:
            # The file (or its containing folder) disappeared between being
            # listed at the start of this scan and being reached here --
            # almost always Radarr/Sonarr renaming or moving it mid-scan
            # (e.g. an upgrade import), not a real problem with AudioCleaner
            # or the file itself. Reported with a specific, reassuring
            # message instead of a raw WinError/errno dump, and *not*
            # counted as a scary failure the way a genuine mkvmerge error
            # is -- a rescan will simply pick the file up at its new
            # location/name.
            result = ProcessResult(
                path=str(f), status="error",
                message="This file (or its folder) is no longer at this location -- "
                        "most likely renamed or moved by other software (Radarr/Sonarr "
                        "import, an antivirus quarantine, etc.) while this scan was "
                        f"running. It will be picked up correctly on the next scan. ({e})",
            )
        except Exception as e:
            # A single bad or racy file (a network-share hiccup, antivirus
            # holding it, or any unexpected bug in the probe/codec chain)
            # must never take the rest of the batch down with it. Without
            # this, one unlucky file aborts run_pipeline entirely -- every
            # file after it in this scan is silently never processed, and
            # the only thing the caller sees is a generic "stopped
            # unexpectedly" failure with no per-file record of what
            # happened. Record it exactly like any other per-file error
            # and move on, the same way the probing phase above already
            # isolates per-file failures.
            result = ProcessResult(
                path=str(f), status="error",
                message=f"Unexpected error while processing this file: {e}",
            )

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
