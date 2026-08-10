from types import SimpleNamespace

from audiocleaner import processor


def track(language="eng", codec_id="A_TRUEHD", channels=8):
    return SimpleNamespace(language=language, codec_id=codec_id, channels=channels)


def video(codec_id="V_MPEG4/ISO/AVC", width=1920, height=1080):
    return SimpleNamespace(codec_id=codec_id, width=width, height=height)


def subtitle(language="eng", codec_id="S_TEXT/UTF8", forced=False, default=False):
    return SimpleNamespace(language=language, codec_id=codec_id, forced=forced, default=default)


def probe_result(audio, subtitles=None):
    return SimpleNamespace(
        error=None,
        video_tracks=[video()],
        audio_tracks=audio,
        subtitle_tracks=subtitles or [],
        chapter_count=10,
        attachment_count=1,
        duration_seconds=100.0,
    )


def test_audio_properties_are_verified_per_track(monkeypatch, tmp_path):
    output = tmp_path / "out.mkv"
    output.write_bytes(b"x" * 100)

    source = probe_result([
        track(codec_id="A_TRUEHD", channels=6),
        track(codec_id="A_AC3", channels=8),
    ])

    # These properties exist in the output, but on different tracks. The old
    # independent-set checks would accept this combination incorrectly.
    output_probe = probe_result([
        track(codec_id="A_TRUEHD", channels=8),
        track(codec_id="A_AC3", channels=6),
    ])
    monkeypatch.setattr(processor, "probe_file", lambda *args, **kwargs: output_probe)

    ok, message = processor._verify_output(
        output,
        source,
        expected_audio_tracks=source.audio_tracks[:1],
        expected_subtitle_tracks=[],
        subtitles_untouched=True,
        source_size=100,
    )
    assert ok is False
    assert "audio track" in message


def test_final_verification_uses_same_validation_rules(monkeypatch, tmp_path):
    output = tmp_path / "out.mkv"
    output.write_bytes(b"x" * 100)
    source = probe_result([track()])

    monkeypatch.setattr(processor, "probe_file", lambda *args, **kwargs: probe_result([track(codec_id="A_AC3")]))

    ok, message = processor._verify_output(
        output,
        source,
        expected_audio_tracks=source.audio_tracks,
        expected_subtitle_tracks=[],
        subtitles_untouched=True,
        source_size=100,
    )
    assert ok is False
    assert "audio track" in message
