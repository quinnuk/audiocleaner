"""
Tests for history.py: recording, querying, and aggregating processing
history (spec sec 23/25/27).
"""
from audiocleaner.history import ProcessingHistory
from audiocleaner.processor import ProcessResult


def _result(path, status="cleaned", bytes_saved=0, removed=0, preview=False):
    return ProcessResult(
        path=path, status=status, kept_codec="truehd" if status == "cleaned" else None,
        removed_track_count=removed, bytes_saved=bytes_saved, preview=preview,
    )


def test_record_and_recent(tmp_path):
    db = tmp_path / "history.db"
    h = ProcessingHistory(db)
    h.record("D:\\Movies", _result("D:\\Movies\\Dune.mkv", bytes_saved=1000, removed=3))
    h.record("D:\\Movies", _result("D:\\Movies\\Barbie.mkv", status="skipped_single_track"))

    entries = h.recent()
    assert len(entries) == 2
    assert entries[0].path == "D:\\Movies\\Barbie.mkv"  # most recent first
    assert entries[1].bytes_saved == 1000
    h.close()


def test_status_filter(tmp_path):
    db = tmp_path / "history.db"
    h = ProcessingHistory(db)
    h.record("F", _result("a.mkv", status="cleaned"))
    h.record("F", _result("b.mkv", status="error"))
    h.record("F", _result("c.mkv", status="error"))

    errors = h.recent(status_filter="error")
    assert len(errors) == 2
    assert all(e.status == "error" for e in errors)
    h.close()


def test_for_path_returns_only_that_files_history(tmp_path):
    db = tmp_path / "history.db"
    h = ProcessingHistory(db)
    h.record("F", _result("a.mkv", status="cleaned"))
    h.record("F", _result("b.mkv", status="cleaned"))
    h.record("F", _result("a.mkv", status="skipped_single_track"))  # a.mkv processed again later

    a_history = h.for_path("a.mkv")
    assert len(a_history) == 2
    assert all(e.path == "a.mkv" for e in a_history)
    assert a_history[0].status == "skipped_single_track"  # most recent first
    h.close()


def test_library_totals_excludes_preview_runs(tmp_path):
    """Preview mode never touches disk, so it must not count towards
    space-recovered totals (sec 27) even though it's still logged."""
    db = tmp_path / "history.db"
    h = ProcessingHistory(db)
    h.record("F", _result("a.mkv", status="cleaned", bytes_saved=1_000_000, removed=2))
    h.record("F", _result("b.mkv", status="cleaned", bytes_saved=500_000, removed=1, preview=True))

    totals = h.library_totals()
    assert totals["files_cleaned"] == 1  # only the non-preview one
    assert totals["bytes_saved"] == 1_000_000
    assert totals["tracks_removed"] == 2
    h.close()


def test_persists_across_reopen(tmp_path):
    db = tmp_path / "history.db"
    h1 = ProcessingHistory(db)
    h1.record("F", _result("a.mkv"))
    h1.close()

    h2 = ProcessingHistory(db)
    entries = h2.recent()
    assert len(entries) == 1
    assert entries[0].path == "a.mkv"
    h2.close()


def test_scanner_run_pipeline_records_history(tmp_path, monkeypatch):
    """run_pipeline should record every processed file to history when no
    explicit ProcessingHistory is passed (it creates its own)."""
    import audiocleaner.scanner as scanner_mod

    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 100)

    def fake_process_file(path, cache=None, **kwargs):
        return _result(str(path), status="cleaned", bytes_saved=42, removed=1)

    monkeypatch.setattr(scanner_mod, "process_file", fake_process_file)
    monkeypatch.setattr(scanner_mod, "probe_file", lambda path, cache=None: None)

    history_db = tmp_path / "test_history.db"
    history = ProcessingHistory(history_db)

    summary = scanner_mod.run_pipeline(tmp_path, history=history)

    assert summary.cleaned == 1
    entries = history.recent()
    assert len(entries) == 1
    assert entries[0].bytes_saved == 42
    history.close()
