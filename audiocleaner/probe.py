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
import sys
import time
from dataclasses import dataclass, field, asdict
from functools import lru_cache
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


def _bundle_dir() -> Optional[Path]:
    """Directory holding files bundled into the frozen exe (PyInstaller
    one-file builds extract these to a temp dir at runtime, exposed via
    sys._MEIPASS). Returns None for a normal (non-frozen) interpreter run."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return None


@lru_cache(maxsize=None)
def find_tool(name: str) -> Optional[str]:
    """
    Locate an external tool's executable, in order of preference:
      1. Bundled alongside the frozen exe (sys._MEIPASS) - this is what
         boot-time autostart launches will use, so it never depends on
         PATH being fresh for whichever user/session context spawned it.
      2. The project root, for convenience when running from source
         during development (where the extracted CLI tool currently sits).
      3. PATH, via shutil.which - last resort, and the only option for
         tools that aren't bundled (e.g. MKVToolNix, currently).
    Result is cached for the life of the process since installed tool
    locations don't change while the app is running.
    """
    exe_name = f"{name}.exe" if os.name == "nt" else name

    bundle = _bundle_dir()
    if bundle:
        candidate = bundle / exe_name
        if candidate.is_file():
            return str(candidate)

    project_root = Path(__file__).resolve().parent.parent
    candidate = project_root / exe_name
    if candidate.is_file():
        return str(candidate)

    return shutil.which(name)


def get_missing_tools() -> list[dict]:
    """Returns a list of missing-tool info dicts (empty list = all present)."""
    missing = []
    for tool, info in REQUIRED_TOOLS.items():
        if find_tool(tool) is None:
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


def _run_json(cmd: list[str], _attempt: int = 0) -> dict:
    # Backoff schedule gives a spun-down HDD real time to wake up (spin-up
    # commonly takes several seconds) rather than giving up after 0.5s.
    _RETRY_DELAYS = [1, 3, 6]  # seconds before attempts 2, 3, 4

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise ExternalToolError(f"Tool not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ExternalToolError(f"{cmd[0]} timed out") from e
    except UnicodeDecodeError as e:
        raise ExternalToolError(f"{cmd[0]} output could not be decoded as UTF-8: {e}") from e
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if not stdout.strip():
        # Empty stdout AND stderr with a clean process exit usually means
        # transient contention - a spun-down drive still waking up, AV
        # briefly holding the file, parallel probes competing for disk -
        # rather than a genuinely broken file. Retry a few times with
        # increasing pauses before treating it as a real failure.
        if _attempt < len(_RETRY_DELAYS):
            time.sleep(_RETRY_DELAYS[_attempt])
            return _run_json(cmd, _attempt=_attempt + 1)
        raise ExternalToolError(
            f"{cmd[0]} produced no output after {_attempt + 1} attempts "
            f"(exit code {proc.returncode}): {stderr.strip()}"
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

    mkvmerge_path = find_tool("mkvmerge")
    if mkvmerge_path is None:
        result.error = "mkvmerge probe failed: MKVToolNix (mkvmerge) not found"
        # Not cached: a missing-tool error should be re-checked every run,
        # not permanently remembered against this file.
        return result

    try:
        mkv_data = _run_json([mkvmerge_path, "-J", str(path)])
    except ExternalToolError as e:
        result.error = f"mkvmerge probe failed: {e}"
        # Not cached: this is very likely transient (spun-down drive still
        # waking, AV briefly holding the file, momentary contention during
        # a big batch). Caching it would "freeze" a one-off hiccup into a
        # permanent failure that gets replayed on every future scan, since
        # the cache key (path/size/mtime) never changes for an untouched
        # file. Leaving it uncached means the next scan gets a clean retry.
        return result

    # mediainfo is best-effort; if it fails we fall back to mkvmerge-only data.
    mi_audio_by_id: dict[int, dict] = {}
    mediainfo_path = find_tool("mediainfo")
    if mediainfo_path is not None:
        try:
            mi_data = _run_json([mediainfo_path, "--Output=JSON", str(path)])
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