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

from .probe import probe_file, ExternalToolError, find_tool
from .codec_rank import select_audio_tracks_to_keep, select_subtitle_tracks_to_keep

# Suppress console window creation for subprocess calls in a windowed
# (console=False) build -- otherwise Windows pops a new console per call.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# PROCESS_MODE_BACKGROUND_BEGIN: tells Windows this process is doing
# background work, which lowers its CPU, memory, *and* I/O priority
# together (stronger than just CPU priority - it's specifically what
# stops a big disk-heavy job like this from starving other programs,
# e.g. Plex, that are reading from the same physical drive at the
# same time). No effect on non-Windows platforms.
_BACKGROUND_MODE = 0x00100000 if os.name == "nt" else 0
_REMUX_CREATE_FLAGS = _NO_WINDOW | _BACKGROUND_MODE


@dataclass
class ProcessResult:
    path: str
    status: str            # "cleaned" | "skipped_single_track" | "no_english" | "error"
    kept_codec: Optional[str] = None
    removed_track_count: int = 0          # audio tracks removed
    removed_subtitle_count: int = 0
    bytes_saved: int = 0
    message: str = ""
    preview: bool = False   # True if this describes what *would* happen; nothing was written


def _atomic_replace(temp_path: Path, original_path: Path):
    # os.replace is atomic on the same filesystem on both Windows and POSIX.
    os.replace(temp_path, original_path)


def process_file(
    path: Path,
    cache=None,
    keep_commentary: bool = False,
    subtitle_filter_enabled: bool = False,
    subtitle_languages=None,
    preview_only: bool = False,
) -> ProcessResult:
    result = probe_file(path, cache=cache)
    if result.error:
        return ProcessResult(path=str(path), status="error", message=result.error)

    if len(result.audio_tracks) == 0:
        return ProcessResult(path=str(path), status="no_english",
                              message="No audio tracks found in file.")

    best_track, codec_key, extra_audio_tracks = select_audio_tracks_to_keep(
        result, keep_commentary=keep_commentary
    )
    if best_track is None:
        return ProcessResult(path=str(path), status="no_english",
                              message="No English audio track found; file skipped.")

    keep_audio_ids = [best_track.track_id] + [t.track_id for t in extra_audio_tracks]
    original_audio_ids = {t.track_id for t in result.audio_tracks}
    audio_unchanged = original_audio_ids == set(keep_audio_ids)

    # Subtitle selection is only evaluated when the feature is switched on;
    # otherwise subtitles are left completely alone, same as before this
    # feature existed.
    subtitle_ids_to_keep = None
    subtitle_unchanged = True
    if subtitle_filter_enabled and result.subtitle_tracks:
        kept_subs = select_subtitle_tracks_to_keep(result, subtitle_languages)
        subtitle_ids_to_keep = [t.track_id for t in kept_subs]
        original_sub_ids = {t.track_id for t in result.subtitle_tracks}
        subtitle_unchanged = original_sub_ids == set(subtitle_ids_to_keep)

    if audio_unchanged and subtitle_unchanged:
        return ProcessResult(path=str(path), status="skipped_single_track",
                              kept_codec=codec_key, preview=preview_only)

    removed_audio_count = len(result.audio_tracks) - len(keep_audio_ids)
    removed_subtitle_count = (
        len(result.subtitle_tracks) - len(subtitle_ids_to_keep)
        if subtitle_ids_to_keep is not None else 0
    )

    if preview_only:
        # Everything above (probing, track selection) is identical to a
        # real run; this is exactly what would happen. Stop here, before
        # any temp file, mkvmerge call, or disk write -- nothing on disk
        # is touched in preview mode. bytes_saved is left at 0 since it's
        # only knowable by actually remuxing and measuring the result.
        return ProcessResult(
            path=str(path), status="cleaned", kept_codec=codec_key,
            removed_track_count=removed_audio_count,
            removed_subtitle_count=removed_subtitle_count,
            preview=True,
        )


    original_size = path.stat().st_size
    temp_path = path.with_name(path.stem + ".ac_tmp" + path.suffix)

    # Clean up any stale temp file from a previous crashed run.
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass

    mkvmerge_path = find_tool("mkvmerge")
    if mkvmerge_path is None:
        return ProcessResult(path=str(path), status="error",
                              message="mkvmerge not found (checked bundled copy and PATH).")

    cmd = [
        mkvmerge_path,
        "-o", str(temp_path),
        "--audio-tracks", ",".join(str(i) for i in keep_audio_ids),
    ]
    if subtitle_filter_enabled and result.subtitle_tracks:
        if subtitle_ids_to_keep:
            cmd += ["--subtitle-tracks", ",".join(str(i) for i in subtitle_ids_to_keep)]
        else:
            # Filtering is on and nothing matched (no kept language, no
            # forced tracks) -- drop subtitles entirely rather than silently
            # keeping everything, which would defeat the point of the filter.
            cmd += ["--no-subtitles"]
    cmd.append(str(path))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            creationflags=_REMUX_CREATE_FLAGS,
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
        stderr_msg = (proc.stderr or "").strip()
        stdout_msg = (proc.stdout or "").strip()
        return ProcessResult(path=str(path), status="error",
                              message=f"mkvmerge failed: {stderr_msg or stdout_msg or '(no output from mkvmerge)'}")

    # --- Verification ---
    ok, verify_msg = _verify_output(
        temp_path, best_track,
        expected_audio_count=len(keep_audio_ids),
        expected_subtitle_count=len(subtitle_ids_to_keep) if subtitle_ids_to_keep is not None else None,
    )
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
        removed_track_count=removed_audio_count,
        removed_subtitle_count=removed_subtitle_count,
        bytes_saved=max(0, original_size - new_size),
    )


def _cleanup_temp(temp_path: Path):
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass


def _verify_output(
    temp_path: Path,
    kept_track,
    expected_audio_count: int,
    expected_subtitle_count: Optional[int],
) -> tuple[bool, str]:
    """Sanity-check the remuxed file before we let it replace the original."""
    try:
        check = probe_file(temp_path, cache=None)
    except ExternalToolError as e:
        return False, str(e)

    if check.error:
        return False, check.error

    if len(check.audio_tracks) != expected_audio_count:
        return False, f"expected {expected_audio_count} audio track(s) in output, found {len(check.audio_tracks)}"

    kept_langs = {t.language for t in check.audio_tracks}
    if kept_track.language not in kept_langs:
        return False, "kept track language mismatch after remux"

    if expected_subtitle_count is not None and len(check.subtitle_tracks) != expected_subtitle_count:
        return False, f"expected {expected_subtitle_count} subtitle track(s) in output, found {len(check.subtitle_tracks)}"

    if temp_path.stat().st_size <= 0:
        return False, "output file is empty"

    return True, "ok"
