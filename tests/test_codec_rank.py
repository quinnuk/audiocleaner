"""
Tests for codec_rank.py: classification of every codec in the priority
list, unknown-codec fallback, English detection, commentary detection, and
deterministic multi-track selection.
"""
import pytest

from audiocleaner.probe import AudioTrackInfo, FileProbeResult
from audiocleaner.codec_rank import (
    classify_audio_track,
    select_audio_tracks_to_keep,
    is_commentary,
)


def _track(
    track_id=1, language="eng", codec_id="", codec_name="",
    channels=6, mi_format="", mi_commercial="", mi_features="",
    track_name="", commentary=False,
):
    return AudioTrackInfo(
        track_id=track_id, language=language, codec_id=codec_id,
        codec_name=codec_name, channels=channels,
        mediainfo_format=mi_format, mediainfo_commercial=mi_commercial,
        mediainfo_additional_features=mi_features,
        track_name=track_name, commentary=commentary,
    )


# --- Codec classification: one case per entry in CODEC_PRIORITY ---

@pytest.mark.parametrize("track,expected", [
    (_track(codec_id="A_TRUEHD", codec_name="TrueHD Atmos", mi_commercial="Dolby TrueHD with Dolby Atmos"), "truehd_atmos"),
    (_track(codec_id="A_DTS", codec_name="DTS-HD", mi_commercial="DTS:X"), "dtsx"),
    (_track(codec_id="A_TRUEHD", codec_name="TrueHD"), "truehd"),
    (_track(codec_id="A_DTS", codec_name="DTS-HD Master Audio", mi_commercial="DTS-HD Master Audio"), "dts_hd_ma"),
    (_track(codec_id="A_PCM/INT/LIT", codec_name="PCM"), "lpcm"),
    (_track(codec_id="A_FLAC", codec_name="FLAC"), "flac"),
    (_track(codec_id="A_EAC3", codec_name="E-AC-3"), "eac3"),
    (_track(codec_id="A_DTS", codec_name="DTS"), "dts"),
    (_track(codec_id="A_AC3", codec_name="AC-3"), "ac3"),
    (_track(codec_id="A_AAC", codec_name="AAC"), "aac"),
    (_track(codec_id="A_MPEG/L3", codec_name="MP3"), "mp3"),
    (_track(codec_id="A_OPUS", codec_name="Opus"), "unknown"),
    (_track(codec_id="A_VORBIS", codec_name="Vorbis"), "unknown"),
])
def test_classify_audio_track(track, expected):
    assert classify_audio_track(track) == expected


def test_unknown_codec_never_crashes_ranking():
    """An unrecognised codec must classify as 'unknown', not raise, and
    must sort worse than every known codec (§7/§8)."""
    from audiocleaner.codec_rank import rank_of
    assert rank_of("unknown") > rank_of("mp3")


# --- English language detection (§10) ---

@pytest.mark.parametrize("lang,expected", [
    ("eng", True), ("en", True), ("en-US", True), ("en-GB", True),
    ("EN", True),
    ("fra", False), ("deu", False), ("spa", False), ("und", False),
    ("", False),
])
def test_english_detection(lang, expected):
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=[_track(language=lang)])
    best, key, _ = select_audio_tracks_to_keep(result)
    assert (best is not None) == expected


def test_unknown_language_not_treated_as_english():
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=[
        _track(track_id=1, language="und", codec_id="A_TRUEHD", codec_name="TrueHD"),
    ])
    best, key, extra = select_audio_tracks_to_keep(result)
    assert best is None  # no English track -> file must be skipped, not guessed at


# --- Commentary detection (§12) ---

def test_commentary_flag_detected():
    t = _track(commentary=True)
    assert is_commentary(t)


def test_commentary_by_name_not_false_positive_on_unrelated_word():
    # "commentary" substring must not trigger on unrelated titles.
    from audiocleaner.probe import AudioTrackInfo
    normal = AudioTrackInfo(
        track_id=1, language="eng", codec_id="A_AC3", codec_name="AC-3",
        channels=6, track_name="Extended Cut", commentary=False,
    )
    assert not is_commentary(normal)


# --- Multi-stage selection determinism (§9) ---

def test_atmos_wins_over_everything_else():
    tracks = [
        _track(track_id=1, codec_id="A_AC3", codec_name="AC-3"),
        _track(track_id=2, codec_id="A_DTS", codec_name="DTS-HD Master Audio", mi_commercial="DTS-HD Master Audio"),
        _track(track_id=3, codec_id="A_TRUEHD", codec_name="TrueHD Atmos", mi_commercial="Dolby TrueHD with Dolby Atmos"),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    best, key, _ = select_audio_tracks_to_keep(result)
    assert key == "truehd_atmos"
    assert best.track_id == 3


def test_same_input_always_same_decision():
    tracks = [
        _track(track_id=1, codec_id="A_AC3", codec_name="AC-3"),
        _track(track_id=2, codec_id="A_DTS", codec_name="DTS"),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    results = {select_audio_tracks_to_keep(result)[1] for _ in range(20)}
    assert results == {"dts"}  # every run picks the same codec, no flapping


def test_non_commentary_preferred_over_commentary_even_if_higher_codec():
    tracks = [
        _track(track_id=1, codec_id="A_AC3", codec_name="AC-3", commentary=False),
        _track(track_id=2, codec_id="A_TRUEHD", codec_name="TrueHD Atmos",
                mi_commercial="Dolby TrueHD with Dolby Atmos", commentary=True),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    best, key, extra = select_audio_tracks_to_keep(result, keep_commentary=False)
    assert best.track_id == 1  # commentary track never becomes "the" kept track
    assert extra == []


def test_keep_commentary_keeps_it_alongside_best_non_commentary():
    tracks = [
        _track(track_id=1, codec_id="A_AC3", codec_name="AC-3", commentary=False),
        _track(track_id=2, codec_id="A_AC3", codec_name="AC-3", commentary=True),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    best, key, extra = select_audio_tracks_to_keep(result, keep_commentary=True)
    assert best.track_id == 1
    assert [t.track_id for t in extra] == [2]
