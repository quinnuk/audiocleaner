"""
Tests for probe.py's cache layer: version-based invalidation and the
Rebuild Cache clear() path (spec §24).
"""
import json

from audiocleaner.probe import ProbeCache, FileProbeResult, AudioTrackInfo, cache_path_for_root
from audiocleaner import config


def _fake_entry(path, scanner_version):
    return {
        "path": str(path),
        "size": 123,
        "mtime": path.stat().st_mtime,
        "audio_tracks": [],
        "subtitle_tracks": [],
        "video_tracks": [],
        "attachment_count": 0,
        "chapter_count": 0,
        "duration_seconds": 0.0,
        "scanner_version": scanner_version,
        "error": None,
    }


def test_cache_hit_on_matching_version(tmp_path):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x" * 123)
    cache_path = tmp_path / ".cache.json"
    cache_path.write_text(json.dumps({str(f): _fake_entry(f, config.SCANNER_VERSION)}))

    cache = ProbeCache(cache_path)
    result = cache.get(f)

    assert result is not None
    assert result.scanner_version == config.SCANNER_VERSION


def test_cache_miss_on_stale_scanner_version(tmp_path):
    """A cache entry written by an older scanner version must be treated
    as a miss and re-probed, not trusted -- otherwise a track-matching fix
    would never actually apply to already-cached files."""
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x" * 123)
    cache_path = tmp_path / ".cache.json"
    cache_path.write_text(json.dumps({str(f): _fake_entry(f, "0-old-version")}))

    cache = ProbeCache(cache_path)
    result = cache.get(f)

    assert result is None


def test_cache_miss_on_size_mtime_mismatch(tmp_path):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x" * 123)
    cache_path = tmp_path / ".cache.json"
    entry = _fake_entry(f, config.SCANNER_VERSION)
    entry["size"] = 999999  # doesn't match actual file size
    cache_path.write_text(json.dumps({str(f): entry}))

    cache = ProbeCache(cache_path)
    assert cache.get(f) is None


def test_clear_wipes_all_entries_without_touching_files(tmp_path):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x" * 123)
    cache_path = tmp_path / ".cache.json"
    cache_path.write_text(json.dumps({str(f): _fake_entry(f, config.SCANNER_VERSION)}))

    cache = ProbeCache(cache_path)
    assert cache.get(f) is not None

    cache.clear()

    assert cache.get(f) is None
    assert f.exists()  # rebuilding the cache never touches media files
    assert f.read_bytes() == b"x" * 123


def test_cache_path_uses_configured_dir_and_separates_roots(tmp_path, monkeypatch):
    configured = tmp_path / "config" / "cache"
    monkeypatch.setenv("AUDIOCLEANER_CACHE_DIR", str(configured))
    first_root = tmp_path / "media-a" / "movies"
    second_root = tmp_path / "media-b" / "movies"

    first = cache_path_for_root(first_root)
    second = cache_path_for_root(second_root)

    assert first != second
    assert first.is_relative_to(configured)
    assert second.is_relative_to(configured)
    assert first.name == config.CACHE_FILENAME
    assert second.name == config.CACHE_FILENAME


def test_cache_path_keeps_default_location_without_override(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIOCLEANER_CACHE_DIR", raising=False)

    assert cache_path_for_root(tmp_path) == tmp_path / config.CACHE_FILENAME


def test_cache_save_creates_configured_parent_directory(tmp_path, monkeypatch):
    configured = tmp_path / "config" / "cache"
    monkeypatch.setenv("AUDIOCLEANER_CACHE_DIR", str(configured))
    media_root = tmp_path / "media" / "movies"

    cache_path = cache_path_for_root(media_root)
    cache = ProbeCache(cache_path)
    cache.save()

    assert cache_path.parent.is_dir()
    assert cache_path.is_file()
    assert cache_path.read_text(encoding="utf-8") == "{}"
