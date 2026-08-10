"""
Tests for probe.py's cache layer: version-based invalidation and the
Rebuild Cache clear() path (spec §24).
"""
import json

from audiocleaner.probe import ProbeCache, FileProbeResult, AudioTrackInfo
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
