"""
QThread wrapper around scanner.run_pipeline so the GUI stays responsive.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .scanner import run_pipeline, scan_subtitle_languages, ScanSummary
from .logger import RunLogger
from .processor import ProcessResult
from .probe import ProbeCache
from .watcher import WatchState, watch_iteration
from .config import CACHE_FILENAME, WATCH_POLL_INTERVAL_SECONDS, WATCH_DEFAULT_SETTLE_SECONDS


class CleanerWorker(QThread):
    progress = Signal(int, int, str, str)   # files_done, files_total, filename, phase
    file_done = Signal(object)              # ProcessResult
    finished_ok = Signal(object)            # ScanSummary
    failed = Signal(str)                    # fatal error message

    def __init__(
        self,
        root: Path,
        parent=None,
        keep_commentary: bool = False,
        subtitle_filter_enabled: bool = False,
        subtitle_languages: Optional[set] = None,
        preview_only: bool = False,
    ):
        super().__init__(parent)
        self.root = root
        self.keep_commentary = keep_commentary
        self.subtitle_filter_enabled = subtitle_filter_enabled
        self.subtitle_languages = subtitle_languages
        self.preview_only = preview_only
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def _should_cancel(self) -> bool:
        return self._cancel_requested

    def run(self):
        logger = None
        try:
            logger = RunLogger(self.root)

            def on_progress(done, total, filename, phase):
                self.progress.emit(done, total, filename, phase)

            def on_file_done(result: ProcessResult):
                logger.log_result(result)
                self.file_done.emit(result)

            summary: ScanSummary = run_pipeline(
                self.root,
                on_progress=on_progress,
                on_file_done=on_file_done,
                should_cancel=self._should_cancel,
                keep_commentary=self.keep_commentary,
                subtitle_filter_enabled=self.subtitle_filter_enabled,
                subtitle_languages=self.subtitle_languages,
                preview_only=self.preview_only,
            )
            logger.log_summary(summary)
            self.finished_ok.emit(summary)
        except Exception as e:  # last-resort catch so the GUI never hangs silently
            self.failed.emit(str(e))
        finally:
            if logger is not None:
                logger.close()


class LanguageScanWorker(QThread):
    """
    Scans one or more folders and reports the combined set of subtitle
    languages found across all of them, used to populate the GUI's
    subtitle-language checklist. Reuses each folder's existing probe cache,
    so this is near-instant on a library that's already been scanned.
    """
    progress = Signal(int, int, str, str)
    finished_ok = Signal(set)     # combined set of language codes found
    failed = Signal(str)

    def __init__(self, roots: list, parent=None):
        super().__init__(parent)
        self.roots = list(roots)

    def run(self):
        try:
            all_langs = set()
            for root in self.roots:
                langs = scan_subtitle_languages(
                    root,
                    on_progress=lambda d, t, f, p: self.progress.emit(d, t, f, p),
                )
                all_langs |= langs
            self.finished_ok.emit(all_langs)
        except Exception as e:
            self.failed.emit(str(e))


class WatchWorker(QThread):
    """
    Runs continuous folder-watch mode: polls indefinitely, processing new
    files once they've stopped changing size for `settle_seconds`. Runs
    until stop() is called.
    """
    file_done = Signal(object)     # ProcessResult
    heartbeat = Signal(str)        # periodic status line, e.g. "watching..."
    failed = Signal(str)

    def __init__(
        self,
        root: Path,
        settle_seconds: int = WATCH_DEFAULT_SETTLE_SECONDS,
        parent=None,
        keep_commentary: bool = False,
        subtitle_filter_enabled: bool = False,
        subtitle_languages: Optional[set] = None,
    ):
        super().__init__(parent)
        self.root = root
        self.settle_seconds = settle_seconds
        self.keep_commentary = keep_commentary
        self.subtitle_filter_enabled = subtitle_filter_enabled
        self.subtitle_languages = subtitle_languages
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True

    def run(self):
        logger = None
        try:
            logger = RunLogger(self.root)
            cache = ProbeCache(self.root / CACHE_FILENAME)
            state = WatchState()
            self.heartbeat.emit(
                f"Watching {self.root} for new files "
                f"(processing after {self.settle_seconds}s of no size change)…"
            )
            while not self._stop_requested:
                results = watch_iteration(
                    self.root, state, cache, self.settle_seconds,
                    keep_commentary=self.keep_commentary,
                    subtitle_filter_enabled=self.subtitle_filter_enabled,
                    subtitle_languages=self.subtitle_languages,
                )
                if results:
                    cache.save()
                for result in results:
                    logger.log_result(result)
                    self.file_done.emit(result)
                # Sleep in small increments so stop() is responsive.
                slept = 0.0
                while slept < WATCH_POLL_INTERVAL_SECONDS and not self._stop_requested:
                    self.msleep(500)
                    slept += 0.5
            self.heartbeat.emit("Watch mode stopped.")
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            if logger is not None:
                logger.close()
