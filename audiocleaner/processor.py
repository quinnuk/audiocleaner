"""
Handles the actual remux: strips unwanted audio tracks via mkvmerge into a
temp file, verifies the result, then atomically replaces the original.
The original file is never touched until verification has succeeded.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .probe import probe_file, FileProbeResult, ExternalToolError
from .codec_rank import select_best_english_track

# Suppress console window creation for subprocess calls in a windowed
# (console=False) build -- otherwise Windows pops a new console per call.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass
class ProcessResult:
    path: str
    status: str            # "cleaned" | "skipped_single_track" | "no_english" | "error"
    kept_codec: Optional[str] = None
    removed_track_count: int = 0
    bytes_saved: int = 0
    message: str = ""


def _atomic_replace(temp_path: Path, original_path: Path):
    # os.replace is atomic on the same filesystem on both Windows and POSIX.
    os.replace(temp_path, original_path)


def process_file(path: Path, cache=None) -> ProcessResult:
    result = probe_file(path, cache=cache)
    if result.error:
        return ProcessResult(path=str(path), status="error", message=result.error)

    if len(result.audio_tracks) == 0:
        return ProcessResult(path=str(path), status="no_english",
                              message="No audio tracks found in file.")

    best_track, codec_key = select_best_english_track(result)
    if best_track is None:
        return ProcessResult(path=str(path), status="no_english",
                              message="No English audio track found; file skipped.")

    if len(result.audio_tracks) == 1:
        # Only one audio track total and it's English -> nothing to strip.
        return ProcessResult(path=str(path), status="skipped_single_track",
                              kept_codec=codec_key)

    removed_count = len(result.audio_tracks) - 1
    original_size = path.stat().st_size
    temp_path = path.with_name(path.stem + ".ac_tmp" + path.suffix)

    # Clean up any stale temp file from a previous crashed run.
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass

    cmd = [
        "mkvmerge",
        "-o", str(temp_path),
        "--audio-tracks", str(best_track.track_id),
        str(path),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        return ProcessResult(path=str(path), status="error",
                              message="mkvmerge not found on PATH.")
    except subprocess.TimeoutExpired:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message="mkvmerge timed out (file may be very large or hung).")

    if proc.returncode == 2 or not temp_path.exists():
        # mkvmerge exit code 2 = error; 0 = success; 1 = warnings (still usable).
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"mkvmerge failed: {proc.stderr.strip() or proc.stdout.strip()}")

    # --- Verification ---
    ok, verify_msg = _verify_output(temp_path, result, best_track)
    if not ok:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"Verification failed, original untouched: {verify_msg}")

    new_size = temp_path.stat().st_size
    try:
        _atomic_replace(temp_path, path)
    except OSError as e:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"Could not replace original file: {e}")

    return ProcessResult(
        path=str(path), status="cleaned", kept_codec=codec_key,
        removed_track_count=removed_count,
        bytes_saved=max(0, original_size - new_size),
    )


def _cleanup_temp(temp_path: Path):
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass


def _verify_output(temp_path: Path, original: FileProbeResult, kept_track) -> tuple[bool, str]:
    """Sanity-check the remuxed file before we let it replace the original."""
    try:
        check = probe_file(temp_path, cache=None)
    except ExternalToolError as e:
        return False, str(e)

    if check.error:
        return False, check.error

    if len(check.audio_tracks) != 1:
        return False, f"expected 1 audio track in output, found {len(check.audio_tracks)}"

    if check.audio_tracks[0].language != kept_track.language:
        return False, "kept track language mismatch after remux"

    if temp_path.stat().st_size <= 0:
        return False, "output file is empty"

    return True, "ok"