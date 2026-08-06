"""
QThread wrapper around scanner.run_pipeline so the GUI stays responsive.
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .scanner import run_pipeline, ScanSummary
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

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
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
            )
            logger.log_summary(summary)
            self.finished_ok.emit(summary)
        except Exception as e:  # last-resort catch so the GUI never hangs silently
            self.failed.emit(str(e))
        finally:
            if logger is not None:
                logger.close()


class WatchWorker(QThread):
    """
    Runs continuous folder-watch mode: polls indefinitely, processing new
    files once they've stopped changing size for `settle_seconds`. Runs
    until stop() is called.
    """
    file_done = Signal(object)     # ProcessResult
    heartbeat = Signal(str)        # periodic status line, e.g. "watching..."
    failed = Signal(str)

    def __init__(self, root: Path, settle_seconds: int = WATCH_DEFAULT_SETTLE_SECONDS, parent=None):
        super().__init__(parent)
        self.root = root
        self.settle_seconds = settle_seconds
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
                results = watch_iteration(self.root, state, cache, self.settle_seconds)
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
