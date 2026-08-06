"""
Probing layer: extracts track metadata from MKV files using mkvmerge (for
container structure) and mediainfo (for accurate codec extension detection,
e.g. Atmos / DTS:X, which mkvmerge does not always surface reliably).

Results are cached on disk keyed by (path, size, mtime) so repeated scans
of an unchanged library are fast.
"""

import json
import os
import subprocess
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Suppress console window creation for subprocess calls in a windowed
# (console=False) build -- otherwise Windows pops a new console per call.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class ExternalToolError(RuntimeError):
    """Raised when mkvmerge or mediainfo cannot be found or fails to run."""


# Info needed to guide a non-technical user to install each dependency.
REQUIRED_TOOLS = {
    "mkvmerge": {
        "label": "MKVToolNix",
        "download_url": "https://mkvtoolnix.download/downloads.html#windows",
        "hint": "During install, tick the option to add it to your PATH.",
    },
    "mediainfo": {
        "label": "MediaInfo (CLI edition)",
        "download_url": "https://mediaarea.net/en/MediaInfo/Download/Windows",
        "hint": "Pick the \"CLI\" download, not the GUI viewer.",
    },
}


def get_missing_tools() -> list[dict]:
    """Returns a list of missing-tool info dicts (empty list = all present)."""
    missing = []
    for tool, info in REQUIRED_TOOLS.items():
        if shutil.which(tool) is None:
            missing.append({"command": tool, **info})
    return missing


def check_tools_available() -> Optional[str]:
    """Returns a plain-text error message if a required tool is missing, else None."""
    missing = get_missing_tools()
    if missing:
        return (
            "Missing required tool(s): "
            + ", ".join(m["label"] for m in missing)
            + ". Install them and ensure they are on PATH."
        )
    return None


@dataclass
class AudioTrackInfo:
    track_id: int
    language: str
    codec_id: str          # mkvmerge codec_id, e.g. "A_TRUEHD"
    codec_name: str        # mkvmerge human-readable codec, e.g. "TrueHD"
    channels: int
    mediainfo_format: str = ""
    mediainfo_commercial: str = ""
    mediainfo_additional_features: str = ""
    default: bool = False
    forced: bool = False


@dataclass
class FileProbeResult:
    path: str
    size: int
    mtime: float
    audio_tracks: list = field(default_factory=list)  # list[AudioTrackInfo]
    error: Optional[str] = None

    def to_json(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_json(d: dict) -> "FileProbeResult":
        tracks = [AudioTrackInfo(**t) for t in d.get("audio_tracks", [])]
        return FileProbeResult(
            path=d["path"], size=d["size"], mtime=d["mtime"],
            audio_tracks=tracks, error=d.get("error"),
        )


class ProbeCache:
    """Simple JSON-backed cache: path -> FileProbeResult, invalidated on
    size/mtime mismatch."""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.cache_path.exists():
            try:
                self._data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def save(self):
        try:
            self.cache_path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # cache is a convenience, never fatal

    def get(self, path: Path) -> Optional[FileProbeResult]:
        entry = self._data.get(str(path))
        if entry is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        if entry["size"] != stat.st_size or entry["mtime"] != stat.st_mtime:
            return None
        return FileProbeResult.from_json(entry)

    def put(self, result: FileProbeResult):
        self._data[result.path] = result.to_json()


def _run_json(cmd: list[str], _retried: bool = False) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise ExternalToolError(f"Tool not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ExternalToolError(f"{cmd[0]} timed out") from e
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if not stdout.strip():
        # Empty stdout AND stderr with a clean process exit usually means
        # transient contention (parallel probing spawns several tool
        # processes at once; AV/IO hiccups can interrupt one of them)
        # rather than a genuinely broken file. Retry once after a brief
        # pause before treating it as a real failure.
        if not _retried:
            time.sleep(0.5)
            return _run_json(cmd, _retried=True)
        raise ExternalToolError(
            f"{cmd[0]} produced no output (exit code {proc.returncode}): {stderr.strip()}"
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ExternalToolError(f"{cmd[0]} returned invalid JSON") from e


def probe_file(path: Path, cache: Optional[ProbeCache] = None) -> FileProbeResult:
    """Probe a single MKV file, using the cache if the file hasn't changed."""
    if cache is not None:
        cached = cache.get(path)
        if cached is not None:
            return cached

    stat = path.stat()
    result = FileProbeResult(path=str(path), size=stat.st_size, mtime=stat.st_mtime)

    try:
        mkv_data = _run_json(["mkvmerge", "-J", str(path)])
    except ExternalToolError as e:
        result.error = f"mkvmerge probe failed: {e}"
        if cache is not None:
            cache.put(result)
        return result

    # mediainfo is best-effort; if it fails we fall back to mkvmerge-only data.
    mi_audio_by_id: dict[int, dict] = {}
    try:
        mi_data = _run_json(["mediainfo", "--Output=JSON", str(path)])
        for track in mi_data.get("media", {}).get("track", []):
            if track.get("@type") == "Audio":
                # mediainfo "StreamOrder" or "ID" roughly maps to mkvmerge track id;
                # we match by position among audio tracks as a robust fallback.
                mi_audio_by_id[len(mi_audio_by_id)] = track
    except ExternalToolError:
        pass

    audio_index = 0
    for track in mkv_data.get("tracks", []):
        if track.get("type") != "audio":
            continue
        props = track.get("properties", {})
        mi_track = mi_audio_by_id.get(audio_index, {})
        result.audio_tracks.append(
            AudioTrackInfo(
                track_id=track.get("id"),
                language=(props.get("language") or props.get("language_ietf") or "und").lower(),
                codec_id=props.get("codec_id", ""),
                codec_name=track.get("codec", ""),
                channels=props.get("audio_channels", 0),
                mediainfo_format=mi_track.get("Format", ""),
                mediainfo_commercial=mi_track.get("Format_Commercial_IfAny", ""),
                mediainfo_additional_features=mi_track.get("Format_AdditionalFeatures", ""),
                default=bool(props.get("default_track", False)),
                forced=bool(props.get("forced_track", False)),
            )
        )
        audio_index += 1

    if cache is not None:
        cache.put(result)
    return result