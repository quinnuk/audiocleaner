from types import SimpleNamespace

from audiocleaner import scanner


def test_preview_is_tracked_separately(monkeypatch, tmp_path):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"movie")

    monkeypatch.setattr(scanner, "probe_file", lambda *args, **kwargs: SimpleNamespace(
        subtitle_tracks=[]
    ))
    monkeypatch.setattr(scanner, "ProcessingHistory", lambda: None)
    monkeypatch.setattr(scanner, "process_file", lambda *args, **kwargs: SimpleNamespace(
        status="cleaned",
        preview=True,
        removed_track_count=2,
        removed_subtitle_count=1,
        bytes_saved=123,
    ))

    summary = scanner.run_pipeline(tmp_path, preview_only=True, probe_workers=1)
    assert summary.preview == 1
    assert summary.cleaned == 0
    assert summary.total_removed_tracks == 0
    assert summary.total_bytes_saved == 0
