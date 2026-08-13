"""
Tests for audiocleaner_log.txt rotation (logger._rotate_if_needed and
RunLogger). Without this, a watch-mode instance left running for months
would grow the log file without bound.
"""
from audiocleaner.logger import RunLogger, _rotate_if_needed


def test_small_log_is_not_rotated(tmp_path):
    log_path = tmp_path / "audiocleaner_log.txt"
    log_path.write_bytes(b"small log contents")

    _rotate_if_needed(log_path, max_bytes=1000, backup_count=2)

    assert log_path.read_bytes() == b"small log contents"
    assert not (tmp_path / "audiocleaner_log.txt.1").exists()


def test_oversized_log_is_rotated_to_dot_1(tmp_path):
    log_path = tmp_path / "audiocleaner_log.txt"
    log_path.write_bytes(b"x" * 1000)

    _rotate_if_needed(log_path, max_bytes=500, backup_count=2)

    assert not log_path.exists()  # current file is gone -> caller opens a fresh one
    assert (tmp_path / "audiocleaner_log.txt.1").read_bytes() == b"x" * 1000


def test_rotation_shifts_older_backups_up(tmp_path):
    log_path = tmp_path / "audiocleaner_log.txt"

    log_path.write_bytes(b"first" * 200)
    _rotate_if_needed(log_path, max_bytes=500, backup_count=2)
    assert (tmp_path / "audiocleaner_log.txt.1").read_bytes() == b"first" * 200

    log_path.write_bytes(b"second" * 200)
    _rotate_if_needed(log_path, max_bytes=500, backup_count=2)
    assert (tmp_path / "audiocleaner_log.txt.1").read_bytes() == b"second" * 200
    assert (tmp_path / "audiocleaner_log.txt.2").read_bytes() == b"first" * 200


def test_rotation_drops_backups_beyond_backup_count(tmp_path):
    log_path = tmp_path / "audiocleaner_log.txt"

    for payload in (b"a" * 600, b"b" * 600, b"c" * 600):
        log_path.write_bytes(payload)
        _rotate_if_needed(log_path, max_bytes=500, backup_count=2)

    # Only .1 and .2 should exist -- the oldest ("a") was pushed out.
    assert (tmp_path / "audiocleaner_log.txt.1").read_bytes() == b"c" * 600
    assert (tmp_path / "audiocleaner_log.txt.2").read_bytes() == b"b" * 600
    assert not (tmp_path / "audiocleaner_log.txt.3").exists()


def test_backup_count_zero_just_deletes_oversized_log(tmp_path):
    log_path = tmp_path / "audiocleaner_log.txt"
    log_path.write_bytes(b"x" * 1000)

    _rotate_if_needed(log_path, max_bytes=500, backup_count=0)

    assert not log_path.exists()
    assert not (tmp_path / "audiocleaner_log.txt.1").exists()


def test_run_logger_rotates_on_open_when_oversized(tmp_path, monkeypatch):
    """RunLogger should rotate an oversized existing log before appending
    its new run header, using the real config threshold."""
    import audiocleaner.logger as logger_mod

    # Use a tiny threshold for the test instead of the real 5 MB default.
    monkeypatch.setattr(logger_mod, "LOG_MAX_BYTES", 50)

    log_path = tmp_path / "audiocleaner_log.txt"
    log_path.write_bytes(b"old run history " * 10)  # > 50 bytes

    rl = RunLogger(tmp_path)
    rl.close()

    assert (tmp_path / "audiocleaner_log.txt.1").exists()
    assert "old run history" in (tmp_path / "audiocleaner_log.txt.1").read_text()
    # Fresh log has only the new run's header, not the old content.
    assert "old run history" not in log_path.read_text()
    assert "AudioCleaner run started" in log_path.read_text()


def test_run_logger_does_not_rotate_small_log(tmp_path):
    log_path = tmp_path / "audiocleaner_log.txt"
    log_path.write_bytes(b"tiny")

    rl = RunLogger(tmp_path)
    rl.close()

    assert not (tmp_path / "audiocleaner_log.txt.1").exists()
    content = log_path.read_text()
    assert "tiny" in content  # old content preserved, just appended to
    assert "AudioCleaner run started" in content
