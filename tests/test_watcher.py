from pathlib import Path
from types import SimpleNamespace

from audiocleaner.watcher import WatchState


def test_processed_path_is_reprocessed_when_file_identity_changes(tmp_path, monkeypatch):
    path = tmp_path / "movie.mkv"
    path.write_bytes(b"first")

    state = WatchState()
    assert state.already_processed(path) is False
    state.mark_processed(path)
    assert state.already_processed(path) is True

    path.write_bytes(b"replacement")
    assert state.already_processed(path) is False


def test_watch_state_retries_errors(monkeypatch, tmp_path):
    from audiocleaner import watcher

    path = tmp_path / "movie.mkv"
    path.write_bytes(b"movie")
    state = WatchState()

    monkeypatch.setattr(watcher.time, "time", lambda: 100.0)
    sighting = state.observe(path)
    assert sighting is not None
    assert state.is_settled(path, 0)

    calls = []

    def fake_process_file(*args, **kwargs):
        calls.append(path)
        return SimpleNamespace(status="error")

    monkeypatch.setattr(watcher, "process_file", fake_process_file)
    cache = SimpleNamespace()

    results = watcher.watch_iteration(tmp_path, state, cache, settle_seconds=0)
    assert len(results) == 1
    assert calls == [path]
    assert state.already_processed(path) is False
