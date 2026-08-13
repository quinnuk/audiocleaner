"""
Headless command-line interface for AudioCleaner.

This exists so AudioCleaner can run somewhere the GUI can't -- a Linux
server, a Docker container, or any Radarr/Sonarr box -- without needing
PySide6 or a display at all. It's a thin wrapper around the same
scanner.run_pipeline / watcher.watch_iteration functions the GUI uses
(via worker.py), so behaviour and safety guarantees are identical; only
the presentation layer differs.

Usage:
    python main.py scan /path/to/library [options]
    python main.py scan /path/to/library --watch [options]

Run `python main.py scan --help` for the full option list.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from .config import (
    APP_NAME, CACHE_FILENAME, DEFAULT_PREFERRED_LANGUAGES,
    WATCH_POLL_INTERVAL_SECONDS, WATCH_DEFAULT_SETTLE_SECONDS,
)
from .logger import RunLogger
from .probe import ProbeCache
from .processor import ProcessResult
from .scanner import run_pipeline, ScanSummary
from .watcher import WatchState, watch_iteration
from .history import ProcessingHistory


def _parse_lang_set(value: Optional[str]) -> Optional[set]:
    if not value:
        return None
    return {v.strip().lower() for v in value.split(",") if v.strip()}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=f"{APP_NAME.lower()} scan",
        description=f"{APP_NAME}: headless scan of an MKV library (no GUI required).",
    )
    p.add_argument("folder", type=str, help="Root folder to scan (recursive).")
    p.add_argument(
        "--watch", action="store_true",
        help="Keep running and clean new files as they arrive, instead of a one-off scan.",
    )
    p.add_argument(
        "--settle-seconds", type=int, default=WATCH_DEFAULT_SETTLE_SECONDS,
        help=f"With --watch, how long a file's size must be unchanged before it's "
             f"processed (default: {WATCH_DEFAULT_SETTLE_SECONDS}s).",
    )
    p.add_argument(
        "--dry-run", "--preview", dest="dry_run", action="store_true",
        help="Report what would change without modifying any files.",
    )
    p.add_argument(
        "--languages", type=str, default=None,
        help="Comma-separated language codes to keep, e.g. 'eng' or 'eng,jpn'. "
             "Default: eng.",
    )
    p.add_argument(
        "--keep-commentary", action="store_true",
        help="Keep commentary track(s) alongside the selected primary track.",
    )
    p.add_argument(
        "--subtitle-filter", action="store_true",
        help="Enable subtitle language filtering (off by default: subtitles untouched).",
    )
    p.add_argument(
        "--subtitle-languages", type=str, default=None,
        help="Comma-separated subtitle language codes to keep when --subtitle-filter "
             "is set, e.g. 'eng'. Forced tracks are always kept regardless.",
    )
    p.add_argument(
        "--max-safety-mode", action="store_true",
        help="Keep a full backup until final verification succeeds, restoring "
             "automatically if it doesn't.",
    )
    p.add_argument(
        "--persistent-backup", action="store_true",
        help="With --max-safety-mode, keep the backup file after a successful run "
             "instead of deleting it.",
    )
    p.add_argument(
        "--probe-workers", type=int, default=4,
        help="Parallel workers for the metadata-scan phase (default: 4).",
    )
    p.add_argument(
        "--no-history", action="store_true",
        help="Don't record this run in the persistent history database.",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="Only print the final summary, not a line per file.",
    )
    return p


def _print_result(result: ProcessResult, quiet: bool) -> None:
    if quiet:
        return
    prefix = {
        "cleaned": "[PREVIEW]" if result.preview else "[CLEANED]",
        "skipped_single_track": "[SKIP]",
        "no_english": "[NO MATCH]",
        "unknown_codec": "[UNKNOWN]",
        "error": "[ERROR]",
    }.get(result.status, f"[{result.status.upper()}]")
    line = f"{prefix} {result.path}"
    if result.status == "cleaned":
        saved = result.bytes_saved / 1_048_576
        line += f" -- kept {result.kept_codec}, removed {result.removed_track_count} track(s)"
        if not result.preview:
            line += f", saved {saved:.1f} MB"
    elif result.message:
        line += f" -- {result.message}"
    print(line)


def _print_summary(summary: ScanSummary, dry_run: bool) -> None:
    label = "Would clean" if dry_run else "Cleaned"
    print("\n--- Summary ---")
    print(f"Scanned: {summary.total_scanned}")
    print(f"{label}: {summary.cleaned}")
    print(f"Skipped (already single matching-language track): {summary.skipped_single_track}")
    print(f"No matching-language audio: {summary.no_english}")
    print(f"Unknown audio format: {summary.unknown_codec}")
    print(f"Errors: {summary.errors}")
    if not dry_run:
        print(f"Disk space recovered: {summary.total_bytes_saved / 1_048_576:.1f} MB")
    print(f"Elapsed: {summary.elapsed_seconds:.1f}s")


def _run_scan(args, root: Path, preferred_languages: Optional[set],
              subtitle_languages: Optional[set]) -> int:
    logger = RunLogger(root)
    history = None
    if not args.no_history:
        try:
            history = ProcessingHistory()
        except Exception:
            history = None  # history is a convenience feature; never block a scan on it

    def on_file_done(result: ProcessResult):
        logger.log_result(result)
        _print_result(result, args.quiet)

    try:
        summary = run_pipeline(
            root,
            on_file_done=on_file_done,
            probe_workers=args.probe_workers,
            keep_commentary=args.keep_commentary,
            subtitle_filter_enabled=args.subtitle_filter,
            subtitle_languages=subtitle_languages,
            preview_only=args.dry_run,
            max_safety_mode=args.max_safety_mode,
            persistent_backup=args.persistent_backup,
            history=history,
            preferred_languages=preferred_languages,
        )
        logger.log_summary(summary)
        _print_summary(summary, args.dry_run)
        return 1 if summary.errors else 0
    finally:
        logger.close()
        if history is not None:
            history.close()


def _run_watch(args, root: Path, preferred_languages: Optional[set],
               subtitle_languages: Optional[set]) -> int:
    if args.dry_run:
        print("--dry-run has no effect with --watch (watch mode always applies "
              "changes as new files settle); ignoring.", file=sys.stderr)

    logger = RunLogger(root)
    cache = ProbeCache(root / CACHE_FILENAME)
    state = WatchState()
    history = None
    if not args.no_history:
        try:
            history = ProcessingHistory()
        except Exception:
            history = None

    print(f"Watching {root} for new files "
          f"(processing after {args.settle_seconds}s of no size change). Ctrl+C to stop.")
    try:
        while True:
            results = watch_iteration(
                root, state, cache, args.settle_seconds,
                keep_commentary=args.keep_commentary,
                subtitle_filter_enabled=args.subtitle_filter,
                subtitle_languages=subtitle_languages,
                max_safety_mode=args.max_safety_mode,
                persistent_backup=args.persistent_backup,
                history=history,
                preferred_languages=preferred_languages,
            )
            if results:
                cache.save()
            for result in results:
                logger.log_result(result)
                _print_result(result, args.quiet)
            time.sleep(WATCH_POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        logger.close()
        if history is not None:
            history.close()


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    root = Path(args.folder).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: '{root}' is not a folder.", file=sys.stderr)
        return 2

    preferred_languages = _parse_lang_set(args.languages) or set(DEFAULT_PREFERRED_LANGUAGES)
    subtitle_languages = _parse_lang_set(args.subtitle_languages)
    if args.subtitle_filter and subtitle_languages is None:
        subtitle_languages = {"eng"}

    if args.watch:
        return _run_watch(args, root, preferred_languages, subtitle_languages)
    return _run_scan(args, root, preferred_languages, subtitle_languages)
