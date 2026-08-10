from pathlib import Path
from types import SimpleNamespace

from audiocleaner import processor


def _probe(path, cache=None):
    return SimpleNamespace(
        error=None,
        path=str(path),
        size=path.stat().st_size,
        audio_tracks=[
            SimpleNamespace(track_id=1, language="eng", codec_id="A_AC3", channels=6),
            SimpleNamespace(track_id=2, language="eng", codec_id="A_AAC", channels=2),
        ],
        subtitle_tracks=[],
        video_tracks=[SimpleNamespace(track_id=0, codec_id="V_MPEG4/ISO/AVC", width=1920, height=1080)],
        chapter_count=0,
        attachment_count=0,
        duration_seconds=10.0,
    )


def _selection(result, keep_commentary=False):
    return result.audio_tracks[0], "ac3", []


def test_existing_backup_is_never_overwritten(monkeypatch, tmp_path):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"original")
    backup = tmp_path / "movie.ac_backup.mkv"
    backup.write_bytes(b"precious-recovery-copy")

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_bytes(b"cleaned")
        return Proc()

    monkeypatch.setattr(processor, "probe_file", _probe)
    monkeypatch.setattr(processor, "select_audio_tracks_to_keep", _selection)
    monkeypatch.setattr(processor, "explain_audio_selection", lambda *args, **kwargs: [])
    monkeypatch.setattr(processor, "find_tool", lambda name: "mkvmerge")
    monkeypatch.setattr(processor.subprocess, "run", fake_run)
    monkeypatch.setattr(processor, "_verify_output", lambda *args, **kwargs: (True, "ok"))

    result = processor.process_file(media, max_safety_mode=True)
    assert result.status == "error"
    assert "already exists" in result.message
    assert backup.read_bytes() == b"precious-recovery-copy"
    assert media.read_bytes() == b"original"


def test_failed_final_verification_restores_original(monkeypatch, tmp_path):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"original")

    calls = {"verify": 0}

    def verify(*args, **kwargs):
        calls["verify"] += 1
        return (calls["verify"] == 1, "bad final artifact")

    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_bytes(b"cleaned")
        return Proc()

    monkeypatch.setattr(processor, "probe_file", _probe)
    monkeypatch.setattr(processor, "select_audio_tracks_to_keep", _selection)
    monkeypatch.setattr(processor, "explain_audio_selection", lambda *args, **kwargs: [])
    monkeypatch.setattr(processor, "find_tool", lambda name: "mkvmerge")
    monkeypatch.setattr(processor.subprocess, "run", fake_run)
    monkeypatch.setattr(processor, "_verify_output", verify)

    result = processor.process_file(media, max_safety_mode=True)
    assert result.status == "error"
    assert result.restored_from_backup is True
    assert media.read_bytes() == b"original"
