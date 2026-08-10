"""
Handles the actual remux: strips unwanted audio tracks via mkvmerge into a
temp file, verifies the result, then atomically replaces the original.
The original file is never touched until verification has succeeded.
"""

import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .probe import probe_file, ExternalToolError, find_tool, FileProbeResult
from .codec_rank import (
    select_audio_tracks_to_keep, select_subtitle_tracks_to_keep,
    explain_audio_selection, explain_subtitle_selection,
)

_DURATION_TOLERANCE_SECONDS = 2.0
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_BACKGROUND_MODE = 0x00100000 if os.name == "nt" else 0
_REMUX_CREATE_FLAGS = _NO_WINDOW | _BACKGROUND_MODE


@dataclass
class BeforeAfterInfo:
    """Snapshot used for the before/after display (spec sec 16)."""
    audio_tracks: int = 0
    video_tracks: int = 0
    subtitle_tracks: int = 0
    size_bytes: int = 0


@dataclass
class ProcessResult:
    path: str
    status: str
    kept_codec: Optional[str] = None
    removed_track_count: int = 0
    removed_subtitle_count: int = 0
    bytes_saved: int = 0
    message: str = ""
    preview: bool = False
    restored_from_backup: bool = False
    audio_decisions: list = field(default_factory=list)
    subtitle_decisions: list = field(default_factory=list)
    before: Optional[BeforeAfterInfo] = None
    after: Optional[BeforeAfterInfo] = None


def _atomic_replace(temp_path: Path, original_path: Path):
    os.replace(temp_path, original_path)


def process_file(
    path: Path,
    cache=None,
    keep_commentary: bool = False,
    subtitle_filter_enabled: bool = False,
    subtitle_languages=None,
    preview_only: bool = False,
    max_safety_mode: bool = False,
    persistent_backup: bool = False,
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

    if codec_key == "unknown":
        return ProcessResult(
            path=str(path), status="unknown_codec",
            message="AudioCleaner found an audio format it does not recognise. "
                    "The file has not been modified.",
        )

    keep_audio_ids = [best_track.track_id] + [t.track_id for t in extra_audio_tracks]
    original_audio_ids = {t.track_id for t in result.audio_tracks}
    audio_unchanged = original_audio_ids == set(keep_audio_ids)
    expected_audio_tracks = [best_track] + list(extra_audio_tracks)
    audio_decisions = explain_audio_selection(result, keep_commentary=keep_commentary)

    subtitle_ids_to_keep = None
    subtitle_unchanged = True
    subtitle_decisions = []
    if subtitle_filter_enabled and result.subtitle_tracks:
        kept_subs = select_subtitle_tracks_to_keep(result, subtitle_languages)
        subtitle_ids_to_keep = [t.track_id for t in kept_subs]
        subtitle_unchanged = {t.track_id for t in result.subtitle_tracks} == set(subtitle_ids_to_keep)
        subtitle_decisions = explain_subtitle_selection(result, subtitle_languages)
    kept_sub_ids = set(subtitle_ids_to_keep or [])
    expected_subtitle_tracks = (
        list(result.subtitle_tracks) if subtitle_ids_to_keep is None
        else [t for t in result.subtitle_tracks if t.track_id in kept_sub_ids]
    )

    before = BeforeAfterInfo(
        audio_tracks=len(result.audio_tracks),
        video_tracks=len(result.video_tracks),
        subtitle_tracks=len(result.subtitle_tracks),
        size_bytes=path.stat().st_size if path.exists() else result.size,
    )

    if audio_unchanged and subtitle_unchanged:
        return ProcessResult(path=str(path), status="skipped_single_track",
                              kept_codec=codec_key, preview=preview_only,
                              audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions,
                              before=before, after=before)

    removed_audio_count = len(result.audio_tracks) - len(keep_audio_ids)
    removed_subtitle_count = (
        len(result.subtitle_tracks) - len(subtitle_ids_to_keep)
        if subtitle_ids_to_keep is not None else 0
    )

    if preview_only:
        preview_after = BeforeAfterInfo(
            audio_tracks=len(keep_audio_ids),
            video_tracks=len(result.video_tracks),
            subtitle_tracks=(len(subtitle_ids_to_keep) if subtitle_ids_to_keep is not None
                              else len(result.subtitle_tracks)),
            size_bytes=0,
        )
        return ProcessResult(
            path=str(path), status="cleaned", kept_codec=codec_key,
            removed_track_count=removed_audio_count,
            removed_subtitle_count=removed_subtitle_count,
            preview=True,
            audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions,
            before=before, after=preview_after,
        )

    original_size = path.stat().st_size
    temp_path = path.with_name(path.stem + ".ac_tmp" + path.suffix)

    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass

    mkvmerge_path = find_tool("mkvmerge")
    if mkvmerge_path is None:
        try:
            find_tool.cache_clear()
        except AttributeError:
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
        try:
            find_tool.cache_clear()
        except AttributeError:
            pass
        return ProcessResult(path=str(path), status="error",
                              message="mkvmerge not found on PATH.")
    except subprocess.TimeoutExpired:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message="mkvmerge timed out (file may be very large or hung).")

    if proc.returncode == 2 or not temp_path.exists():
        _cleanup_temp(temp_path)
        stderr_msg = (proc.stderr or "").strip()
        stdout_msg = (proc.stdout or "").strip()
        return ProcessResult(path=str(path), status="error",
                              message=f"mkvmerge failed: {stderr_msg or stdout_msg or '(no output from mkvmerge)'}",
                              audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions, before=before)

    ok, verify_msg = _verify_output(
        temp_path, result,
        expected_audio_tracks=expected_audio_tracks,
        expected_subtitle_tracks=expected_subtitle_tracks,
        subtitles_untouched=not (subtitle_filter_enabled and result.subtitle_tracks),
        source_size=original_size,
    )
    if not ok:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"Verification failed, original untouched: {verify_msg}",
                              audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions, before=before)

    new_size = temp_path.stat().st_size

    backup_path = None
    if max_safety_mode:
        backup_path = path.with_name(path.stem + ".ac_backup" + path.suffix)
        if backup_path.exists():
            _cleanup_temp(temp_path)
            return ProcessResult(
                path=str(path), status="error",
                message=f"Maximum Safety Mode backup already exists: {backup_path}. "
                        "Refusing to overwrite the existing recovery copy.",
                audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions, before=before,
            )
        try:
            shutil.copy2(path, backup_path)
        except OSError as e:
            _cleanup_temp(temp_path)
            return ProcessResult(path=str(path), status="error",
                                  message=f"Could not create Maximum Safety Mode backup, "
                                          f"original untouched: {e}")

    try:
        _atomic_replace(temp_path, path)
    except OSError as e:
        _cleanup_temp(temp_path)
        if backup_path and backup_path.exists() and not persistent_backup:
            _cleanup_temp(backup_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"Could not replace original file: {e}")

    final_ok, final_msg = _verify_output(
        path, result,
        expected_audio_tracks=expected_audio_tracks,
        expected_subtitle_tracks=expected_subtitle_tracks,
        subtitles_untouched=not (subtitle_filter_enabled and result.subtitle_tracks),
        source_size=original_size,
    )
    if not final_ok:
        if backup_path is not None and backup_path.exists():
            try:
                shutil.copy2(backup_path, path)
                if not persistent_backup:
                    _cleanup_temp(backup_path)
                return ProcessResult(
                    path=str(path), status="error", restored_from_backup=True,
                    message="Final verification failed after replacement; "
                            "original restored from Maximum Safety Mode backup. "
                            f"Verification detail: {final_msg}",
                )
            except OSError as e:
                return ProcessResult(
                    path=str(path), status="error",
                    message=f"Final verification failed after replacement, AND the "
                            f"backup could not be restored automatically: {e}. "
                            f"Backup is at {backup_path}",
                )
        return ProcessResult(
            path=str(path), status="error",
            message="Final verification failed after replacement. "
                    "The replaced file may be inconsistent -- check it manually. "
                    "Enable Maximum Safety Mode to allow automatic recovery here. "
                    f"Verification detail: {final_msg}",
        )

    final_check = probe_file(path, cache=None)
    if cache is not None:
        cache.put(final_check)

    if backup_path is not None and backup_path.exists() and not persistent_backup:
        _cleanup_temp(backup_path)

    after = BeforeAfterInfo(
        audio_tracks=len(final_check.audio_tracks),
        video_tracks=len(final_check.video_tracks),
        subtitle_tracks=len(final_check.subtitle_tracks),
        size_bytes=new_size,
    )

    return ProcessResult(
        path=str(path), status="cleaned", kept_codec=codec_key,
        removed_track_count=removed_audio_count,
        removed_subtitle_count=removed_subtitle_count,
        bytes_saved=max(0, original_size - new_size),
        audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions,
        before=before, after=after,
    )


def _cleanup_temp(temp_path: Path):
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass


def _audio_signature(track) -> tuple:
    return (
        (track.language or "").lower(),
        (track.codec_id or "").upper(),
        int(track.channels or 0),
    )


def _video_signature(track) -> tuple:
    return (
        (track.codec_id or "").upper(),
        int(track.width or 0),
        int(track.height or 0),
    )


def _subtitle_signature(track) -> tuple:
    return (
        (track.language or "").lower(),
        (track.codec_id or "").upper(),
        bool(track.forced),
        bool(track.default),
    )


def _verify_output(
    output_path: Path,
    source: FileProbeResult,
    expected_audio_tracks: list,
    expected_subtitle_tracks: list,
    subtitles_untouched: bool,
    source_size: int,
) -> tuple[bool, str]:
    """Validate the exact artifact that is about to be or has been installed."""
    try:
        check = probe_file(output_path, cache=None)
    except (ExternalToolError, OSError) as e:
        return False, str(e)

    if check.error:
        return False, check.error

    try:
        out_size = output_path.stat().st_size
    except OSError as e:
        return False, f"could not stat output: {e}"
    if out_size <= 0:
        return False, "output file is empty"
    if source_size and out_size < source_size * 0.05:
        return False, (f"output ({out_size} bytes) is implausibly small compared to "
                       f"source ({source_size} bytes) for an audio/subtitle-only change")

    if len(check.video_tracks) != len(source.video_tracks):
        return False, f"expected {len(source.video_tracks)} video track(s), found {len(check.video_tracks)}"
    if Counter(_video_signature(t) for t in check.video_tracks) != Counter(_video_signature(t) for t in source.video_tracks):
        return False, "video track codec/resolution changed unexpectedly"

    if len(check.audio_tracks) != len(expected_audio_tracks):
        return False, f"expected {len(expected_audio_tracks)} audio track(s) in output, found {len(check.audio_tracks)}"
    expected_audio = Counter(_audio_signature(t) for t in expected_audio_tracks)
    actual_audio = Counter(_audio_signature(t) for t in check.audio_tracks)
    if actual_audio != expected_audio:
        return False, f"audio track identities/properties changed unexpectedly: expected {sorted(expected_audio.elements())}, found {sorted(actual_audio.elements())}"

    expected_subtitles = source.subtitle_tracks if subtitles_untouched else expected_subtitle_tracks
    if len(check.subtitle_tracks) != len(expected_subtitles):
        return False, f"expected {len(expected_subtitles)} subtitle track(s), found {len(check.subtitle_tracks)}"
    if Counter(_subtitle_signature(t) for t in check.subtitle_tracks) != Counter(_subtitle_signature(t) for t in expected_subtitles):
        return False, "subtitle track properties changed unexpectedly"

    if check.chapter_count != source.chapter_count:
        return False, f"chapter count changed: {source.chapter_count} -> {check.chapter_count}"
    if check.attachment_count != source.attachment_count:
        return False, f"attachment count changed: {source.attachment_count} -> {check.attachment_count}"

    if source.duration_seconds and check.duration_seconds:
        if abs(source.duration_seconds - check.duration_seconds) > _DURATION_TOLERANCE_SECONDS:
            return False, (f"duration changed beyond tolerance: "
                           f"{source.duration_seconds:.1f}s -> {check.duration_seconds:.1f}s")

    return True, "ok"
