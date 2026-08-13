"""
Tests for cli.py, the headless (no-GUI) command-line interface.

These monkeypatch scanner.process_file / probe_file the same way
test_history.py does, so no real mkvmerge/mediainfo/PySide6 is needed to
run them -- cli.py itself never imports anything from gui.py or
worker.py, so these also double as a check that `python main.py scan`
genuinely works without PySide6 installed.
"""
from pathlib import Path

import audiocleaner.scanner as scanner_mod
from audiocleaner import cli
from audiocleaner.processor import ProcessResult


def _result(path, status="cleaned", bytes_saved=0, removed=0, kept_codec="truehd", preview=False):
    return ProcessResult(
        path=str(path), status=status, kept_codec=kept_codec if status == "cleaned" else None,
        removed_track_count=removed, bytes_saved=bytes_saved, preview=preview,
    )


def _patch_pipeline(monkeypatch, results):
    """Make run_pipeline's underlying process_file return canned results
    in order, one per discovered file, without touching real files."""
    it = iter(results)
    monkeypatch.setattr(scanner_mod, "process_file", lambda path, cache=None, **kw: next(it))
    monkeypatch.setattr(scanner_mod, "probe_file", lambda path, cache=None: None)


# --- argument parsing ---

def test_parse_lang_set():
    assert cli._parse_lang_set("eng,jpn") == {"eng", "jpn"}
    assert cli._parse_lang_set(" eng , JPN ") == {"eng", "jpn"}
    assert cli._parse_lang_set(None) is None
    assert cli._parse_lang_set("") is None


def test_arg_parser_defaults():
    args = cli.build_arg_parser().parse_args(["/some/folder"])
    assert args.folder == "/some/folder"
    assert args.watch is False
    assert args.dry_run is False
    assert args.languages is None
    assert args.keep_commentary is False
    assert args.subtitle_filter is False
    assert args.probe_workers == 4


def test_arg_parser_dry_run_alias():
    # --preview is an alias for --dry-run (dest="dry_run" for both)
    args = cli.build_arg_parser().parse_args(["/f", "--preview"])
    assert args.dry_run is True


# --- main() / scan path ---

def test_main_rejects_nonexistent_folder(tmp_path, capsys):
    # cli.main() takes argv *without* the leading "scan" token -- main.py
    # strips that before dispatching -- so just pass the folder path.
    missing = tmp_path / "does_not_exist"
    rc = cli.main([str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "not a folder" in err


def test_main_empty_folder_reports_zero_and_exits_0(tmp_path, capsys):
    rc = cli.main([str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Scanned: 0" in out


def test_main_scan_prints_per_file_results_and_summary(tmp_path, monkeypatch, capsys):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 10)
    _patch_pipeline(monkeypatch, [
        _result(f, status="cleaned", bytes_saved=1_048_576, removed=2, kept_codec="truehd_atmos"),
    ])

    rc = cli.main([str(tmp_path), "--no-history"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "[CLEANED]" in out
    assert "truehd_atmos" in out
    assert "removed 2 track(s)" in out
    assert "saved 1.0 MB" in out
    assert "Cleaned: 1" in out


def test_main_scan_error_status_sets_nonzero_exit_code(tmp_path, monkeypatch, capsys):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 10)
    _patch_pipeline(monkeypatch, [
        _result(f, status="error"),
    ])

    rc = cli.main([str(tmp_path), "--no-history"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "[ERROR]" in out
    assert "Errors: 1" in out


def test_main_dry_run_labels_output_as_preview(tmp_path, monkeypatch, capsys):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 10)
    _patch_pipeline(monkeypatch, [
        _result(f, status="cleaned", bytes_saved=0, removed=1, preview=True),
    ])

    rc = cli.main([str(tmp_path), "--dry-run", "--no-history"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "[PREVIEW]" in out
    assert "Would clean: 1" in out
    assert "saved" not in out  # preview never reports bytes saved -- nothing was measured


def test_main_quiet_suppresses_per_file_lines(tmp_path, monkeypatch, capsys):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 10)
    _patch_pipeline(monkeypatch, [
        _result(f, status="cleaned", bytes_saved=100, removed=1),
    ])

    rc = cli.main([str(tmp_path), "--quiet", "--no-history"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "[CLEANED]" not in out
    assert "Cleaned: 1" in out


def test_main_languages_flag_is_forwarded_to_pipeline(tmp_path, monkeypatch, capsys):
    """Doesn't need real language-selection behaviour (that's tested in
    test_codec_rank.py) -- just confirms cli.py parses --languages and
    passes the resulting set through to run_pipeline."""
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 10)

    captured = {}

    def fake_run_pipeline(root, **kwargs):
        captured["preferred_languages"] = kwargs.get("preferred_languages")
        from audiocleaner.scanner import ScanSummary
        return ScanSummary(total_scanned=0)

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)

    cli.main([str(tmp_path), "--languages", "eng,jpn", "--no-history"])

    assert captured["preferred_languages"] == {"eng", "jpn"}


def test_main_writes_log_file(tmp_path, monkeypatch):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 10)
    _patch_pipeline(monkeypatch, [_result(f, status="skipped_single_track", kept_codec="truehd")])

    cli.main([str(tmp_path), "--no-history"])

    log_path = tmp_path / "audiocleaner_log.txt"
    assert log_path.exists()
    assert "SKIPPED" in log_path.read_text()
