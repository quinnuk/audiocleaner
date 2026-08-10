"""
Tests for the decision-explanation and before/after reporting added to
codec_rank.py / processor.py (spec sec 15/16).
"""
import pytest

from audiocleaner.probe import AudioTrackInfo, SubtitleTrackInfo, FileProbeResult
from audiocleaner.codec_rank import explain_audio_selection, explain_subtitle_selection, track_label


def _audio(track_id, language="eng", codec_id="A_AC3", codec_name="AC-3",
           channels=6, mi_commercial="", commentary=False, track_name=""):
    return AudioTrackInfo(
        track_id=track_id, language=language, codec_id=codec_id, codec_name=codec_name,
        channels=channels, mediainfo_commercial=mi_commercial,
        commentary=commentary, track_name=track_name,
    )


def test_track_label_format():
    t = _audio(1, codec_id="A_TRUEHD", codec_name="TrueHD Atmos", mi_commercial="Dolby TrueHD with Dolby Atmos", channels=8)
    assert track_label(t) == "English — Dolby TrueHD + Atmos 8ch"


def test_kept_track_has_reason_referencing_priority():
    tracks = [
        _audio(1, codec_id="A_AC3", codec_name="AC-3"),
        _audio(2, codec_id="A_TRUEHD", codec_name="TrueHD Atmos", mi_commercial="Dolby TrueHD with Dolby Atmos"),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    decisions = explain_audio_selection(result)

    kept = [d for d in decisions if d.kept]
    removed = [d for d in decisions if not d.kept]
    assert len(kept) == 1 and kept[0].track_id == 2
    assert "Highest-ranked" in kept[0].reason
    assert len(removed) == 1 and removed[0].track_id == 1
    assert "Lower priority" in removed[0].reason
    assert "TrueHD" in removed[0].reason  # names what beat it


def test_foreign_track_reason_names_language():
    tracks = [
        _audio(1, codec_id="A_AC3", codec_name="AC-3", language="eng"),
        _audio(2, codec_id="A_AC3", codec_name="AC-3", language="fra"),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    decisions = explain_audio_selection(result)
    fra_decision = next(d for d in decisions if d.track_id == 2)
    assert not fra_decision.kept
    assert "Not an English track" in fra_decision.reason
    assert "fra" in fra_decision.reason


def test_commentary_removed_reason_when_off():
    tracks = [
        _audio(1, codec_id="A_AC3", codec_name="AC-3", commentary=False),
        _audio(2, codec_id="A_AC3", codec_name="AC-3", commentary=True),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    decisions = explain_audio_selection(result, keep_commentary=False)
    commentary_decision = next(d for d in decisions if d.track_id == 2)
    assert not commentary_decision.kept
    assert "Commentary" in commentary_decision.reason
    assert "off" in commentary_decision.reason


def test_commentary_kept_reason_when_enabled():
    tracks = [
        _audio(1, codec_id="A_AC3", codec_name="AC-3", commentary=False),
        _audio(2, codec_id="A_AC3", codec_name="AC-3", commentary=True),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)
    decisions = explain_audio_selection(result, keep_commentary=True)
    commentary_decision = next(d for d in decisions if d.track_id == 2)
    assert commentary_decision.kept
    assert "enabled" in commentary_decision.reason


def test_subtitle_explanation_forced_always_kept():
    subs = [
        SubtitleTrackInfo(track_id=1, language="eng"),
        SubtitleTrackInfo(track_id=2, language="jpn", forced=True),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, subtitle_tracks=subs)
    decisions = explain_subtitle_selection(result, keep_languages={"eng"})

    eng = next(d for d in decisions if d.track_id == 1)
    jpn = next(d for d in decisions if d.track_id == 2)
    assert eng.kept and "Language selected" in eng.reason
    assert jpn.kept and "forced" in jpn.reason.lower()


def test_subtitle_explanation_unselected_language_removed():
    subs = [SubtitleTrackInfo(track_id=1, language="ger")]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, subtitle_tracks=subs)
    decisions = explain_subtitle_selection(result, keep_languages={"eng"})
    assert not decisions[0].kept
    assert "ger" in decisions[0].reason


def test_decisions_always_consistent_with_actual_selection():
    """The explanation must never disagree with what select_audio_tracks_to_keep
    would actually do -- explain_audio_selection is built directly on top
    of it precisely so they can't drift apart."""
    from audiocleaner.codec_rank import select_audio_tracks_to_keep
    tracks = [
        _audio(1, codec_id="A_DTS", codec_name="DTS-HD Master Audio", mi_commercial="DTS-HD Master Audio"),
        _audio(2, codec_id="A_AC3", codec_name="AC-3"),
        _audio(3, codec_id="A_AC3", codec_name="AC-3", commentary=True),
    ]
    result = FileProbeResult(path="x.mkv", size=1, mtime=0.0, audio_tracks=tracks)

    best, key, extra = select_audio_tracks_to_keep(result, keep_commentary=True)
    decisions = explain_audio_selection(result, keep_commentary=True)

    actual_kept_ids = {best.track_id} | {t.track_id for t in extra}
    decision_kept_ids = {d.track_id for d in decisions if d.kept}
    assert actual_kept_ids == decision_kept_ids
