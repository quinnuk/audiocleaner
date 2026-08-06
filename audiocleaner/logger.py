"""
Simple, human-readable logging to a text file in the target root folder.
"""

import datetime
from pathlib import Path

from .config import LOG_FILENAME
from .processor import ProcessResult
from .config import CODEC_LABELS


class RunLogger:
    def __init__(self, root: Path):
        self.log_path = root / LOG_FILENAME
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
        elif result.status == "error":
            line = f"[{ts}] ERROR    {result.path} -- {result.message}\n"
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
            f"Errors: {summary.errors}\n"
            f"Audio tracks removed: {summary.total_removed_tracks}\n"
            f"Disk space recovered: {summary.total_bytes_saved / 1_048_576:.1f} MB\n"
            f"Elapsed: {summary.elapsed_seconds:.1f}s\n"
            "================================================\n"
        )
        self._fh.flush()

    def close(self):
        self._fh.close()
