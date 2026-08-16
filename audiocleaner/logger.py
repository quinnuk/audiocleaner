"""
Simple, human-readable logging to a text file in the target root folder.
"""

import datetime
from pathlib import Path

from .config import LOG_FILENAME, LOG_MAX_BYTES, LOG_BACKUP_COUNT
from .processor import ProcessResult
from .config import CODEC_LABELS


def _rotate_if_needed(log_path: Path, max_bytes: int = LOG_MAX_BYTES,
                       backup_count: int = LOG_BACKUP_COUNT) -> None:
    """If log_path exists and has grown past max_bytes, roll it: .N -> .N+1
    (oldest beyond backup_count is discarded), then current -> .1, leaving
    a fresh file to be opened for append. A watch-mode instance left
    running for months would otherwise grow this file without bound.
    """
    try:
        if not log_path.exists() or log_path.stat().st_size < max_bytes:
            return
    except OSError:
        return

    # Shift existing backups up by one (.2 -> .3, .1 -> .2, ...), dropping
    # anything that would land beyond backup_count.
    for i in range(backup_count - 1, 0, -1):
        src = log_path.with_name(f"{log_path.name}.{i}")
        dst = log_path.with_name(f"{log_path.name}.{i + 1}")
        if src.exists():
            try:
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
            except OSError:
                pass  # rotation is best-effort; never block logging over it

    if backup_count > 0:
        dst = log_path.with_name(f"{log_path.name}.1")
        try:
            if dst.exists():
                dst.unlink()
            log_path.rename(dst)
        except OSError:
            pass
    else:
        try:
            log_path.unlink()
        except OSError:
            pass


class RunLogger:
    def __init__(self, root: Path):
        self.log_path = root / LOG_FILENAME
        # Read the module-level constants at call time (not as bound
        # defaults) so tests can monkeypatch logger.LOG_MAX_BYTES /
        # logger.LOG_BACKUP_COUNT and have it take effect here.
        _rotate_if_needed(self.log_path, max_bytes=LOG_MAX_BYTES, backup_count=LOG_BACKUP_COUNT)
        self._fh = open(self.log_path, "a", encoding="utf-8")
        self._write_header()

    def _write_header(self):
        self._fh.write(
            f"\n===== AudioCleaner run started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n"
        )
        self._fh.flush()

    def log_result(self, result: ProcessResult):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        if result.status == "cleaned":
            codec = CODEC_LABELS.get(result.kept_codec, result.kept_codec)
            line = (
                f"[{ts}] CLEANED  {result.path}\n"
                f"           kept: {codec} | removed {result.removed_track_count} track(s) "
                f"| saved {result.bytes_saved / 1_048_576:.1f} MB\n"
            )
        elif result.status == "skipped_single_track":
            codec = CODEC_LABELS.get(result.kept_codec, result.kept_codec)
            line = f"[{ts}] SKIPPED  {result.path} (already only track: {codec})\n"
        elif result.status == "no_english":
            line = f"[{ts}] NO ENGLISH AUDIO  {result.path} -- {result.message}\n"
        elif result.status == "unknown_codec":
            line = f"[{ts}] UNKNOWN FORMAT  {result.path} -- {result.message}\n"
        elif result.status == "error":
            restored = " (restored from backup)" if result.restored_from_backup else ""
            line = f"[{ts}] ERROR    {result.path}{restored} -- {result.message}\n"
        else:
            line = f"[{ts}] {result.status.upper()}  {result.path}\n"
        self._fh.write(line)
        self._fh.flush()

    def log_summary(self, summary):
        self._fh.write(
            "\n--- Summary ---\n"
            f"Scanned: {summary.total_scanned}\n"
            f"Cleaned: {summary.cleaned}\n"
            f"Skipped (already single English track): {summary.skipped_single_track}\n"
            f"No English audio: {summary.no_english}\n"
            f"Unknown audio format: {summary.unknown_codec}\n"
            f"Errors: {summary.errors}\n"
            f"Audio tracks removed: {summary.total_removed_tracks}\n"
            f"Subtitle tracks removed: {summary.total_removed_subtitle_tracks}\n"
            f"Disk space recovered: {summary.total_bytes_saved / 1_048_576:.1f} MB\n"
            f"Elapsed: {summary.elapsed_seconds:.1f}s\n"
            "================================================\n"
        )
        self._fh.flush()

    def close(self):
        self._fh.close()
