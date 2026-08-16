"""
Safety-critical tests for processor.py. These exercise the core promise of
the app: the original file is never modified unless verification of the
temp output has fully succeeded, and an unknown/unclear situation results
in SKIP, never a guess.

Real mkvmerge/mediainfo calls are avoided (no binary MKV fixtures needed
for these) by monkeypatching probe_file and find_tool, so these tests run
anywhere Python + pytest run, including this container.
"""
import os
from pathlib import Path

import pytest

from audiocleaner import processor as processor_mod
from audiocleaner.probe import AudioTrackInfo, VideoTrackInfo, FileProbeResult


def _mkv_bytes(n=2048):
    # Not a real MKV -- process_file never actually parses this content in
    # these tests, since probe_file and mkvmerge are monkeypatched.
    return b"\x00" * n


def _video():
    return VideoTrackInfo(track_id=0, codec_id="V_MPEGH/ISO/HEVC", codec_name="HEVC",
                           width=1920, height=1080, language="und")


def _audio(track_id, codec_id="A_AC3", codec_name="AC-3", channels=6, language="eng"):
    return AudioTrackInfo(track_id=track_id, language=language, codec_id=codec_id,
                           codec_name=codec_name, channels=channels)


def test_unknown_codec_skips_without_touching_file(tmp_path, monkeypatch):
    """§8: an unrecognised audio codec must leave the file completely
    untouched and report 'unknown_codec', never guess."""
    f = tmp_path / "movie.mkv"
    original_bytes = _mkv_bytes()
    f.write_bytes(original_bytes)

    probe_result = FileProbeResult(
        path=str(f), size=len(original_bytes), mtime=f.stat().st_mtime,
        video_tracks=[_video()],
        audio_tracks=[_audio(1, codec_id="A_OPUS", codec_name="Opus")],
    )
    monkeypatch.setattr(processor_mod, "probe_file", lambda path, cache=None: probe_result)

    result = processor_mod.process_file(f, cache=None)

    assert result.status == "unknown_codec"
    assert f.read_bytes() == original_bytes  # untouched, byte for byte
    assert not any(p.suffix == ".mkv" and p != f for p in tmp_path.iterdir())  # no temp/backup left behind


def test_no_english_audio_skips_without_touching_file(tmp_path, monkeypatch):
    f = tmp_path / "movie.mkv"
    original_bytes = _mkv_bytes()
    f.write_bytes(original_bytes)

    probe_result = FileProbeResult(
        path=str(f), size=len(original_bytes), mtime=f.stat().st_mtime,
        video_tracks=[_video()],
        audio_tracks=[_audio(1, language="fra")],
    )
    monkeypatch.setattr(processor_mod, "probe_file", lambda path, cache=None: probe_result)

    result = processor_mod.process_file(f, cache=None)

    assert result.status == "no_english"
    assert f.read_bytes() == original_bytes


def test_verification_failure_leaves_original_untouched_and_deletes_temp(tmp_path, monkeypatch):
    """§4/§33: if the remuxed output doesn't match what was expected
    (simulated here as a wrong audio track count), the original must be
    left completely alone and the temp file must not survive."""
    f = tmp_path / "movie.mkv"
    original_bytes = _mkv_bytes()
    f.write_bytes(original_bytes)

    source_probe = FileProbeResult(
        path=str(f), size=len(original_bytes), mtime=f.stat().st_mtime,
        video_tracks=[_video()],
        audio_tracks=[_audio(1, codec_id="A_TRUEHD", codec_name="TrueHD Atmos"),
                       _audio(2, codec_id="A_AC3", codec_name="AC-3")],
    )
    # The "bad" output claims to still have 2 audio tracks (verification
    # bug scenario) -- simulate a genuinely broken remux instead.
    bad_output_probe = FileProbeResult(
        path="", size=0, mtime=0.0,
        video_tracks=[_video()],
        audio_tracks=[],  # mkvmerge silently dropped everything -- must be caught
    )

    call_state = {"probe_calls": 0}

    def fake_probe(path, cache=None):
        call_state["probe_calls"] += 1
        if call_state["probe_calls"] == 1:
            return source_probe
        return bad_output_probe

    monkeypatch.setattr(processor_mod, "probe_file", fake_probe)
    monkeypatch.setattr(processor_mod, "find_tool", lambda name: "/usr/bin/mkvmerge")

    def fake_run_remux(cmd, on_progress=None, should_cancel=None, timeout_seconds=None):
        # Simulate mkvmerge producing *some* output file so the temp-file
        # existence check passes, but verification (via fake_probe) must
        # still catch that its contents are wrong.
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_bytes(b"\x00" * 512)
        return (0, "", False, False)  # returncode, output_text, cancelled, timed_out

    monkeypatch.setattr(processor_mod, "_run_remux", fake_run_remux)

    result = processor_mod.process_file(f, cache=None)

    assert result.status == "error"
    assert "Verification failed" in result.message
    assert f.read_bytes() == original_bytes  # original completely untouched
    leftover = [p for p in tmp_path.iterdir() if p != f]
    assert leftover == []  # temp file cleaned up, nothing else left behind


def test_max_safety_mode_restores_original_on_final_verification_failure(tmp_path, monkeypatch):
    """§5/§22: if the post-replacement re-probe fails, Maximum Safety Mode
    must restore the original from its backup rather than leave a broken
    file in place."""
    f = tmp_path / "movie.mkv"
    original_bytes = b"ORIGINAL" * 100
    f.write_bytes(original_bytes)

    source_probe = FileProbeResult(
        path=str(f), size=len(original_bytes), mtime=f.stat().st_mtime,
        video_tracks=[_video()],
        audio_tracks=[_audio(1, codec_id="A_TRUEHD", codec_name="TrueHD Atmos"),
                       _audio(2, codec_id="A_AC3", codec_name="AC-3")],
    )
    good_temp_probe = FileProbeResult(
        path="", size=0, mtime=0.0,
        video_tracks=[_video()],
        audio_tracks=[_audio(1, codec_id="A_TRUEHD", codec_name="TrueHD Atmos")],
    )
    # Post-replacement re-probe reports something broken (e.g. corrupted
    # during the OS-level replace) -- final safety net must trigger.
    broken_final_probe = FileProbeResult(path="", size=0, mtime=0.0, error="corrupt file")

    call_state = {"n": 0}

    def fake_probe(path, cache=None):
        call_state["n"] += 1
        if call_state["n"] == 1:
            return source_probe       # initial probe
        elif call_state["n"] == 2:
            return good_temp_probe    # pre-replacement verification of temp file
        else:
            return broken_final_probe  # post-replacement final check

    monkeypatch.setattr(processor_mod, "probe_file", fake_probe)
    monkeypatch.setattr(processor_mod, "find_tool", lambda name: "/usr/bin/mkvmerge")

    def fake_run_remux(cmd, on_progress=None, should_cancel=None, timeout_seconds=None):
        out_path = Path(cmd[cmd.index("-o") + 1])
        out_path.write_bytes(b"CLEANED" * 50)
        return (0, "", False, False)

    monkeypatch.setattr(processor_mod, "_run_remux", fake_run_remux)

    result = processor_mod.process_file(f, cache=None, max_safety_mode=True)

    assert result.status == "error"
    assert result.restored_from_backup is True
    assert f.read_bytes() == original_bytes  # restored to exactly the original content


def test_preview_mode_never_writes_to_disk(tmp_path, monkeypatch):
    f = tmp_path / "movie.mkv"
    original_bytes = _mkv_bytes()
    f.write_bytes(original_bytes)

    probe_result = FileProbeResult(
        path=str(f), size=len(original_bytes), mtime=f.stat().st_mtime,
        video_tracks=[_video()],
        audio_tracks=[_audio(1, codec_id="A_TRUEHD", codec_name="TrueHD Atmos"),
                       _audio(2, codec_id="A_AC3", codec_name="AC-3")],
    )
    monkeypatch.setattr(processor_mod, "probe_file", lambda path, cache=None: probe_result)

    result = processor_mod.process_file(f, cache=None, preview_only=True)

    assert result.preview is True
    assert result.status == "cleaned"
    assert f.read_bytes() == original_bytes
    assert list(tmp_path.iterdir()) == [f]  # nothing else created
