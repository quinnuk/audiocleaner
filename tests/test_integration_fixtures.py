"""
Integration tests: run the real probe -> select -> remux -> verify pipeline
against synthetic MKV fixtures (tests/fixtures/, see build_fixtures.py for
provenance -- no copyrighted media). Unlike test_processor_safety.py, this
suite does NOT mock probe_file or mkvmerge; it exercises the actual
external tools, so it's skipped automatically if mkvmerge/mediainfo aren't
installed (e.g. a minimal dev machine) rather than failing.
"""
import shutil
from pathlib import Path

import pytest

from audiocleaner.probe import find_tool, probe_file
from audiocleaner.processor import process_file
from audiocleaner.codec_rank import select_audio_tracks_to_keep

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

pytestmark = pytest.mark.skipif(
    find_tool("mkvmerge") is None or find_tool("mediainfo") is None,
    reason="mkvmerge/mediainfo not installed -- integration tests need the real tools",
)


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    src = FIXTURES_DIR / name
    if not src.exists():
        pytest.skip(f"fixture {name} missing -- run tests/fixtures/build_fixtures.py")
    dst = tmp_path / name
    shutil.copy2(src, dst)
    return dst


def test_multi_track_probe_matches_tracks_correctly(tmp_path):
    """Real end-to-end check of the sec 6 track-matching fix: each audio
    track's mediainfo enrichment must correspond to *its own* stream, not
    a neighbour's -- verified against a real 5-audio-track MKV, not mocks."""
    f = _copy_fixture("multi_track.mkv", tmp_path)
    result = probe_file(f, cache=None)

    assert result.error is None
    assert len(result.audio_tracks) == 5
    assert len(result.subtitle_tracks) == 2
    assert len(result.video_tracks) == 1

    by_codec_id = {t.codec_id: t for t in result.audio_tracks}
    # Each track's mediainfo-derived format must be consistent with its own
    # mkvmerge codec_id, never a different track's.
    assert "AC-3" in by_codec_id["A_AC3"].mediainfo_format or by_codec_id["A_AC3"].mediainfo_commercial == "Dolby Digital"
    assert by_codec_id["A_DTS"].mediainfo_format == "DTS"
    assert by_codec_id["A_TRUEHD"].mediainfo_commercial == "Dolby TrueHD"

    # Commentary track correctly flagged via mkvmerge's own property.
    commentary_tracks = [t for t in result.audio_tracks if t.commentary]
    assert len(commentary_tracks) == 1
    assert commentary_tracks[0].track_name == "Director Commentary"

    # Forced French subtitle preserved as forced.
    forced_subs = [t for t in result.subtitle_tracks if t.forced]
    assert len(forced_subs) == 1
    assert forced_subs[0].language == "fre"


def test_multi_track_selects_truehd_over_dts_and_ac3(tmp_path):
    f = _copy_fixture("multi_track.mkv", tmp_path)
    result = probe_file(f, cache=None)
    best, key, extra = select_audio_tracks_to_keep(result, keep_commentary=False)

    assert key == "truehd"
    assert best.codec_id == "A_TRUEHD"
    assert extra == []  # commentary excluded by default


def test_full_clean_run_keeps_only_truehd_and_preserves_everything_else(tmp_path):
    """End-to-end: process a real multi-track file, verify the actual
    remuxed output has exactly one audio track, and video/subtitles are
    completely untouched."""
    f = _copy_fixture("multi_track.mkv", tmp_path)

    result = process_file(f, cache=None, keep_commentary=False)

    assert result.status == "cleaned"
    assert result.kept_codec == "truehd"
    assert result.removed_track_count == 4

    final = probe_file(f, cache=None)
    assert final.error is None
    assert len(final.audio_tracks) == 1
    assert final.audio_tracks[0].codec_id == "A_TRUEHD"
    assert len(final.video_tracks) == 1
    assert len(final.subtitle_tracks) == 2  # subtitles untouched (filtering was off)


def test_no_english_audio_real_file_left_untouched(tmp_path):
    f = _copy_fixture("no_english.mkv", tmp_path)
    original_bytes = f.read_bytes()

    result = process_file(f, cache=None)

    assert result.status == "no_english"
    assert f.read_bytes() == original_bytes


def test_single_track_real_file_reported_already_clean(tmp_path):
    f = _copy_fixture("single_track.mkv", tmp_path)
    original_bytes = f.read_bytes()

    result = process_file(f, cache=None)

    assert result.status == "skipped_single_track"
    assert f.read_bytes() == original_bytes  # not even rewritten to an identical copy


def test_unknown_codec_real_file_left_untouched(tmp_path):
    f = _copy_fixture("unknown_codec.mkv", tmp_path)
    original_bytes = f.read_bytes()

    result = process_file(f, cache=None)

    assert result.status == "unknown_codec"
    assert f.read_bytes() == original_bytes


def test_preview_mode_real_file_reports_correctly_without_writing(tmp_path):
    f = _copy_fixture("multi_track.mkv", tmp_path)
    original_bytes = f.read_bytes()

    result = process_file(f, cache=None, preview_only=True)

    assert result.status == "cleaned"
    assert result.preview is True
    assert result.kept_codec == "truehd"
    assert result.removed_track_count == 4
    assert f.read_bytes() == original_bytes  # preview never writes


def test_keep_commentary_real_file_keeps_both_tracks(tmp_path):
    f = _copy_fixture("multi_track.mkv", tmp_path)

    result = process_file(f, cache=None, keep_commentary=True)

    assert result.status == "cleaned"
    final = probe_file(f, cache=None)
    assert len(final.audio_tracks) == 2
    codecs = {t.codec_id for t in final.audio_tracks}
    commentary_present = any(t.commentary for t in final.audio_tracks)
    assert commentary_present
    assert "A_TRUEHD" in codecs  # best non-commentary track still the primary keep


def test_max_safety_mode_real_file_cleans_successfully_and_leaves_no_backup(tmp_path):
    """A normal successful run under Maximum Safety Mode should still end
    with just the cleaned file -- backup created and removed automatically
    once final verification passes (sec 22)."""
    f = _copy_fixture("multi_track.mkv", tmp_path)

    result = process_file(f, cache=None, max_safety_mode=True, persistent_backup=False)

    assert result.status == "cleaned"
    leftover = [p.name for p in tmp_path.iterdir() if p != f]
    assert leftover == []  # backup cleaned up, no stray temp files


def test_max_safety_mode_persistent_backup_real_file_keeps_backup(tmp_path):
    f = _copy_fixture("multi_track.mkv", tmp_path)

    result = process_file(f, cache=None, max_safety_mode=True, persistent_backup=True)

    assert result.status == "cleaned"
    backups = [p for p in tmp_path.iterdir() if p.name.endswith(".ac_backup.mkv")]
    assert len(backups) == 1
