"""
Handles the actual remux: strips unwanted audio tracks via mkvmerge into a
temp file, verifies the result, then atomically replaces the original.
The original file is never touched until verification has succeeded.
"""

import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .probe import probe_file, ExternalToolError, find_tool, FileProbeResult
from .codec_rank import (
    select_audio_tracks_to_keep, select_subtitle_tracks_to_keep,
    explain_audio_selection, explain_subtitle_selection,
)
from .config import TEMP_FILE_SUFFIX, BACKUP_FILE_SUFFIX

# Tolerance for container-level duration drift between input and output
# (remuxing can shift the reported duration by a tiny amount even with no
# content change). Anything beyond this is treated as a real mismatch.
_DURATION_TOLERANCE_SECONDS = 2.0

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

# Hard ceiling on a single remux, in case mkvmerge genuinely hangs (a spun
# -down drive that never wakes, AV holding the file indefinitely, etc).
# This used to be enforced by a single blocking subprocess.run() call --
# which meant a slow-but-healthy remux of a huge file was indistinguishable
# from a truly hung one, and neither could be cancelled or reported on
# until this timeout finally fired. _run_remux() below reports real
# progress and can be interrupted well before this ceiling.
#
# There used to be just one flat 3600s (1h) wall-clock cap from the start
# of the remux, with no way to tell "genuinely stuck" apart from "just
# slow". A 4K remux with lossless TrueHD/Atmos tracks is easily 60-100+ GB;
# on an external/network drive, under antivirus scanning, or with a
# concurrent Plex read from the same disk, that can legitimately take well
# over an hour and still be making steady progress the whole time. Killing
# it there discarded real, in-progress work.
#
# So there are now two separate checks:
#   - a STALL timeout: if mkvmerge's own reported progress hasn't
#     advanced *at all* for this long, it's genuinely stuck (this is the
#     one that actually fires in normal operation, whether the file is
#     1 GB or 100 GB)
#   - an ABSOLUTE timeout: a generous backstop in case something produces
#     nonstop-but-meaningless progress output forever, or no progress
#     output at all for the whole run
_REMUX_STALL_TIMEOUT_SECONDS = 20 * 60      # 20 min with zero progress movement
_REMUX_ABSOLUTE_TIMEOUT_SECONDS = 6 * 3600  # 6h backstop regardless of progress

# mkvmerge's --gui-mode prints machine-readable status lines of the form
# "#GUI#progress 42%" as it works, instead of staying silent until it
# exits. This is what lets AudioCleaner show real per-file progress
# during a remux instead of appearing to freeze on a large file.
_GUI_PROGRESS_RE = re.compile(r"#GUI#progress\s+(\d+)%")


class ProcessingCancelled(Exception):
    """Raised by _run_remux (via process_file) when should_cancel() returns
    True while a remux is actually in progress -- lets scanner.run_pipeline
    stop immediately instead of only being able to cancel between files."""


def _run_remux(
    cmd: list[str],
    on_progress: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    timeout_seconds: int = _REMUX_ABSOLUTE_TIMEOUT_SECONDS,
    stall_timeout_seconds: int = _REMUX_STALL_TIMEOUT_SECONDS,
) -> tuple[int, str, bool, bool]:
    """
    Runs an mkvmerge command with --gui-mode and streams its stdout on a
    background thread so this function can poll for cancellation/timeout
    every `poll_interval` seconds *regardless* of whether mkvmerge is
    currently producing output -- a plain blocking subprocess.run() call
    could not be interrupted at all until it finished on its own, up to
    the full timeout.

    Two independent timeouts apply: `stall_timeout_seconds` fires if
    mkvmerge's own reported progress hasn't advanced at all for that long
    (this is what actually catches a genuinely hung process, regardless of
    file size), and `timeout_seconds` is a generous absolute backstop.

    Returns (returncode, output_text, cancelled, timed_out). output_text
    is mkvmerge's non-progress stdout/stderr (merged), for error messages.
    """
    poll_interval = 0.5
    start = time.time()
    last_progress_pct = -1
    last_progress_time = start

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merged: avoids a separate-pipe deadlock risk
            encoding="utf-8",
            errors="replace",
            creationflags=_REMUX_CREATE_FLAGS,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return 127, "mkvmerge not found on PATH.", False, False

    line_queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def _reader():
        try:
            for line in proc.stdout:
                line_queue.put(line)
        except Exception:
            pass
        finally:
            line_queue.put(None)  # sentinel: stream closed

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    output_lines: list[str] = []
    cancelled = False
    timed_out = False
    stream_closed = False

    while True:
        try:
            line = line_queue.get(timeout=poll_interval)
        except queue.Empty:
            line = ""  # nothing new this tick; fall through to the checks below

        if line is None:
            stream_closed = True
        elif line:
            match = _GUI_PROGRESS_RE.search(line)
            if match:
                pct = int(match.group(1))
                if pct > last_progress_pct:
                    # Real forward movement -- reset the stall clock. A
                    # huge file sitting at the same percentage for a long
                    # stretch (spun-down drive, AV holding it) is exactly
                    # what this is meant to catch; one that's merely slow
                    # keeps ticking pct upward and never trips it.
                    last_progress_pct = pct
                    last_progress_time = time.time()
                if on_progress:
                    try:
                        on_progress(min(1.0, pct / 100))
                    except Exception:
                        pass  # progress reporting must never abort the remux
            elif not line.startswith("#GUI#"):
                output_lines.append(line.rstrip("\n"))

        if should_cancel and should_cancel():
            cancelled = True
            proc.terminate()
            break
        now = time.time()
        if now - start > timeout_seconds:
            timed_out = True
            proc.terminate()
            break
        if now - last_progress_time > stall_timeout_seconds:
            timed_out = True
            proc.terminate()
            break
        if stream_closed and proc.poll() is not None:
            break

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass  # nothing more we can do; OS will reap it eventually

    return (proc.returncode if proc.returncode is not None else -1,
            "\n".join(output_lines), cancelled, timed_out)


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
    # "cleaned" | "skipped_single_track" | "no_english" | "unknown_codec" | "error"
    status: str
    kept_codec: Optional[str] = None
    removed_track_count: int = 0          # audio tracks removed
    removed_subtitle_count: int = 0
    bytes_saved: int = 0
    message: str = ""
    preview: bool = False   # True if this describes what *would* happen; nothing was written
    restored_from_backup: bool = False    # True if Max Safety Mode had to roll back
    # Per-track KEEP/REMOVE explanations (spec sec 15). Empty when the file
    # was skipped before track selection ran (error / no audio at all).
    audio_decisions: list = field(default_factory=list)      # list[AudioTrackDecision]
    subtitle_decisions: list = field(default_factory=list)   # list[SubtitleTrackDecision], only when filtering is on
    before: Optional[BeforeAfterInfo] = None
    after: Optional[BeforeAfterInfo] = None


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
    max_safety_mode: bool = False,
    persistent_backup: bool = False,
    preferred_languages=None,
    on_remux_progress: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ProcessResult:
    result = probe_file(path, cache=cache)
    if result.error:
        return ProcessResult(path=str(path), status="error", message=result.error)

    if len(result.audio_tracks) == 0:
        return ProcessResult(path=str(path), status="no_english",
                              message="No audio tracks found in file.")

    best_track, codec_key, extra_audio_tracks = select_audio_tracks_to_keep(
        result, keep_commentary=keep_commentary, preferred_languages=preferred_languages
    )
    if best_track is None:
        return ProcessResult(path=str(path), status="no_english",
                              message="No audio track in the preferred language(s) found; file skipped.")

    # Safety principle: if AudioCleaner can't confidently classify the
    # audio it would keep, it must not touch the file. An "unknown" codec
    # here means every candidate English track (or the only one available)
    # didn't match any known codec signature -- guessing at how to rank or
    # verify it is exactly the unsafe behaviour this app must avoid.
    if codec_key == "unknown":
        return ProcessResult(
            path=str(path), status="unknown_codec",
            message="AudioCleaner found an audio format it does not recognise. "
                    "The file has not been modified.",
        )

    keep_audio_ids = [best_track.track_id] + [t.track_id for t in extra_audio_tracks]
    original_audio_ids = {t.track_id for t in result.audio_tracks}
    audio_unchanged = original_audio_ids == set(keep_audio_ids)

    audio_decisions = explain_audio_selection(
        result, keep_commentary=keep_commentary, preferred_languages=preferred_languages
    )

    # Subtitle selection is only evaluated when the feature is switched on;
    # otherwise subtitles are left completely alone, same as before this
    # feature existed.
    subtitle_ids_to_keep = None
    subtitle_unchanged = True
    subtitle_decisions = []
    if subtitle_filter_enabled and result.subtitle_tracks:
        kept_subs = select_subtitle_tracks_to_keep(result, subtitle_languages)
        subtitle_ids_to_keep = [t.track_id for t in kept_subs]
        original_sub_ids = {t.track_id for t in result.subtitle_tracks}
        subtitle_unchanged = original_sub_ids == set(subtitle_ids_to_keep)
        subtitle_decisions = explain_subtitle_selection(result, subtitle_languages)

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
        # Everything above (probing, track selection) is identical to a
        # real run; this is exactly what would happen. Stop here, before
        # any temp file, mkvmerge call, or disk write -- nothing on disk
        # is touched in preview mode. bytes_saved/after.size_bytes are
        # left at 0/unknown since actual output size is only knowable by
        # actually remuxing and measuring the result.
        preview_after = BeforeAfterInfo(
            audio_tracks=len(keep_audio_ids),
            video_tracks=len(result.video_tracks),
            subtitle_tracks=(len(subtitle_ids_to_keep) if subtitle_ids_to_keep is not None
                              else len(result.subtitle_tracks)),
            size_bytes=0,  # unknowable without actually remuxing
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
    temp_path = path.with_name(path.stem + TEMP_FILE_SUFFIX + path.suffix)

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
        "--gui-mode",  # emits "#GUI#progress N%" lines so we can report real progress
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

    # stdin is explicitly closed (not inherited): mkvmerge never reads from
    # it, and on Windows the parent's stdin handle can be invalid in some
    # launch contexts (a windowed/console-less process, or a test runner
    # that's redirected stdio) -- inheriting it there raises "OSError:
    # [WinError 6] The handle is invalid" before the child process even
    # starts. See _run_remux() for why this isn't a plain subprocess.run().
    returncode, output_text, cancelled, timed_out = _run_remux(
        cmd, on_progress=on_remux_progress, should_cancel=should_cancel,
    )

    if cancelled:
        _cleanup_temp(temp_path)
        raise ProcessingCancelled(str(path))

    if timed_out:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"mkvmerge made no progress for over "
                                      f"{_REMUX_STALL_TIMEOUT_SECONDS // 60} minutes (or ran past "
                                      f"the {_REMUX_ABSOLUTE_TIMEOUT_SECONDS // 3600}h absolute limit) "
                                      f"-- the drive or antivirus may be holding the file, or it may "
                                      f"be genuinely stuck. A large file that's still making steady "
                                      f"progress is not affected by this. Original untouched.",
                              audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions, before=before)

    if returncode not in (0, 1) or not temp_path.exists():
        # mkvmerge exit code 0 = success; 1 = warnings (still usable);
        # 2 = error. Explicitly checking "not in (0, 1)" (rather than just
        # "== 2") also catches a process that ended with any other exit
        # code -- killed by the OS/antivirus, a disk-full condition, etc.
        # -- instead of silently treating an unrecognised code as success
        # and hoping _verify_output() below catches the bad output.
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"mkvmerge failed: {output_text.strip() or '(no output from mkvmerge)'}",
                              audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions, before=before)

    # --- Verification (pre-replacement): compare temp output against the
    # original probe, not just against expected counts, so we catch e.g. a
    # wrong track surviving in place of the right one, or a video/chapter/
    # attachment side-effect of a bad mkvmerge run. ---
    ok, verify_msg = _verify_output(
        temp_path, result, best_track,
        expected_audio_ids=keep_audio_ids,
        expected_subtitle_count=len(subtitle_ids_to_keep) if subtitle_ids_to_keep is not None else None,
        subtitles_untouched=not (subtitle_filter_enabled and result.subtitle_tracks),
    )
    if not ok:
        _cleanup_temp(temp_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"Verification failed, original untouched: {verify_msg}",
                              audio_decisions=audio_decisions, subtitle_decisions=subtitle_decisions, before=before)

    new_size = temp_path.stat().st_size

    backup_path = None
    if max_safety_mode:
        backup_path = path.with_name(path.stem + BACKUP_FILE_SUFFIX + path.suffix)
        if backup_path.exists():
            try:
                backup_path.unlink()
            except OSError:
                pass
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
        if backup_path:
            _cleanup_temp(backup_path)
        return ProcessResult(path=str(path), status="error",
                              message=f"Could not replace original file: {e}")

    # --- Final post-replacement verification (§5): never assume
    # os.replace() succeeding means the job is actually done -- reopen the
    # file that's now sitting where the original was and probe it fresh.
    final_check = probe_file(path, cache=None)
    final_ok = (
        final_check.error is None
        and len(final_check.audio_tracks) == len(keep_audio_ids)
    )
    if not final_ok:
        if backup_path is not None and backup_path.exists():
            try:
                os.replace(backup_path, path)
                return ProcessResult(
                    path=str(path), status="error", restored_from_backup=True,
                    message="Final verification failed after replacement; "
                            "original restored from Maximum Safety Mode backup.",
                )
            except OSError as e:
                return ProcessResult(
                    path=str(path), status="error",
                    message=f"Final verification failed after replacement, AND the "
                            f"backup could not be restored automatically: {e}. "
                            f"Backup is at {backup_path}",
                )
        # No backup available (Maximum Safety Mode was off): the file at
        # `path` is whatever survived the replace. We can't undo it, but we
        # must not report success.
        return ProcessResult(
            path=str(path), status="error",
            message="Final verification failed after replacement. "
                    "The replaced file may be inconsistent -- check it manually. "
                    "Enable Maximum Safety Mode to allow automatic recovery here.",
        )

    if backup_path is not None and backup_path.exists() and not persistent_backup:
        try:
            backup_path.unlink()
        except OSError:
            pass  # non-fatal: a leftover backup is safe, just extra disk usage

    if cache is not None:
        cache.put(final_check)

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


def _verify_output(
    temp_path: Path,
    source: FileProbeResult,
    kept_track,
    expected_audio_ids: list,
    expected_subtitle_count: Optional[int],
    subtitles_untouched: bool,
) -> tuple[bool, str]:
    """Sanity-check the remuxed file before we let it replace the original.

    Compares the temp output against the *source* probe (not just bare
    counts), covering video/audio/subtitle/chapter/attachment/duration/size
    per the spec's verification requirements. Anything unexpected here means
    the temp file is discarded and the original is never touched."""
    try:
        check = probe_file(temp_path, cache=None)
    except ExternalToolError as e:
        return False, str(e)

    if check.error:
        return False, check.error

    # --- File size sanity ---
    out_size = temp_path.stat().st_size
    if out_size <= 0:
        return False, "output file is empty"
    src_size = Path(source.path).stat().st_size if Path(source.path).exists() else None
    if src_size and out_size < src_size * 0.05:
        # A remux that only removes some audio/subtitle streams should
        # never shrink a file to a sliver of its original size -- that
        # pattern indicates something went badly wrong (e.g. video got
        # dropped), not a legitimate space saving.
        return False, (f"output ({out_size} bytes) is implausibly small compared to "
                        f"source ({src_size} bytes) for an audio/subtitle-only change")

    # --- Video: must be completely unchanged (this app never touches video) ---
    if len(check.video_tracks) != len(source.video_tracks):
        return False, f"expected {len(source.video_tracks)} video track(s), found {len(check.video_tracks)}"
    for src_v, out_v in zip(source.video_tracks, check.video_tracks):
        if src_v.codec_id != out_v.codec_id or (src_v.width, src_v.height) != (out_v.width, out_v.height):
            return False, "video track codec/resolution changed unexpectedly"

    # --- Audio: exact track count, and every kept track's key properties
    # (language, codec, channels) must still be present in the output ---
    if len(check.audio_tracks) != len(expected_audio_ids):
        return False, f"expected {len(expected_audio_ids)} audio track(s) in output, found {len(check.audio_tracks)}"

    kept_langs = {t.language for t in check.audio_tracks}
    if kept_track.language not in kept_langs:
        return False, "kept track language mismatch after remux"

    out_codec_ids = {t.codec_id for t in check.audio_tracks}
    if kept_track.codec_id and kept_track.codec_id not in out_codec_ids:
        return False, "kept track codec changed unexpectedly after remux"

    out_channel_counts = {t.channels for t in check.audio_tracks}
    if kept_track.channels and kept_track.channels not in out_channel_counts:
        return False, "kept track channel count changed unexpectedly after remux"

    # --- Subtitles ---
    if subtitles_untouched:
        if len(check.subtitle_tracks) != len(source.subtitle_tracks):
            return False, (f"subtitle filtering is off but subtitle count changed: "
                            f"{len(source.subtitle_tracks)} -> {len(check.subtitle_tracks)}")
        src_sub_langs = sorted(t.language for t in source.subtitle_tracks)
        out_sub_langs = sorted(t.language for t in check.subtitle_tracks)
        if src_sub_langs != out_sub_langs:
            return False, "subtitle languages changed unexpectedly with filtering off"
    elif expected_subtitle_count is not None and len(check.subtitle_tracks) != expected_subtitle_count:
        return False, f"expected {expected_subtitle_count} subtitle track(s) in output, found {len(check.subtitle_tracks)}"

    # --- Chapters & attachments: preserved unless a future feature says
    # otherwise (none currently does) ---
    if check.chapter_count != source.chapter_count:
        return False, f"chapter count changed: {source.chapter_count} -> {check.chapter_count}"
    if check.attachment_count != source.attachment_count:
        return False, f"attachment count changed: {source.attachment_count} -> {check.attachment_count}"

    # --- Duration ---
    if source.duration_seconds and check.duration_seconds:
        if abs(source.duration_seconds - check.duration_seconds) > _DURATION_TOLERANCE_SECONDS:
            return False, (f"duration changed beyond tolerance: "
                            f"{source.duration_seconds:.1f}s -> {check.duration_seconds:.1f}s")

    return True, "ok"
