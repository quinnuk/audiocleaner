"""
Classifies an AudioTrackInfo into one of the internal codec keys defined in
config.CODEC_PRIORITY, and selects the best English track for a file.

Atmos and DTS:X are extensions layered on top of a core codec (TrueHD / DTS)
and are not always reported by mkvmerge, so we prefer mediainfo's commercial
name / additional-features fields when available, and fall back to
mkvmerge's codec_name string (recent MKVToolNix versions do append
"Atmos" to TrueHD tracks it detects).
"""

from typing import Optional

from .config import ENGLISH_LANG_CODES, CODEC_RANK
from .probe import AudioTrackInfo, FileProbeResult


def _is_english(track: AudioTrackInfo) -> bool:
    return track.language.lower() in ENGLISH_LANG_CODES


def classify_audio_track(track: AudioTrackInfo) -> str:
    """Return an internal codec key (see config.CODEC_PRIORITY) for a track."""
    codec_id = (track.codec_id or "").upper()
    codec_name = (track.codec_name or "").lower()
    commercial = (track.mediainfo_commercial or "").lower()
    features = (track.mediainfo_additional_features or "").lower()
    mi_format = (track.mediainfo_format or "").lower()

    is_truehd = "TRUEHD" in codec_id or "truehd" in codec_name or "mlp" in mi_format
    is_dts = "DTS" in codec_id or "dts" in codec_name or "dts" in mi_format

    has_atmos = "atmos" in commercial or "atmos" in codec_name
    has_dtsx = (
        "dts:x" in commercial or "dts-x" in commercial or "dtsx" in commercial
        or "xll x" in features or ":x" in codec_name
    )

    if is_truehd and has_atmos:
        return "truehd_atmos"
    if is_dts and has_dtsx:
        return "dtsx"
    if is_truehd:
        return "truehd"
    if is_dts and ("hd master" in commercial or "hd ma" in codec_name or "dts-hd master" in mi_format
                    or "MA" in codec_id):
        return "dts_hd_ma"
    if "PCM" in codec_id or "pcm" in codec_name:
        return "lpcm"
    if "FLAC" in codec_id or "flac" in codec_name:
        return "flac"
    if "EAC3" in codec_id or "E-AC-3" in codec_id or "e-ac-3" in codec_name or "eac3" in codec_name:
        return "eac3"
    if is_dts:
        return "dts"
    if "AC3" in codec_id or "ac-3" in codec_name or "ac3" in codec_name:
        return "ac3"
    if "AAC" in codec_id or "aac" in codec_name:
        return "aac"
    if "MP3" in codec_id or "mp3" in codec_name or "L3" in codec_id:
        return "mp3"
    return "unknown"


def rank_of(codec_key: str) -> int:
    """Lower is better; unknown codecs sort last."""
    return CODEC_RANK.get(codec_key, len(CODEC_RANK))


def select_best_english_track(
    result: FileProbeResult,
) -> tuple[Optional[AudioTrackInfo], Optional[str]]:
    """
    Returns (best_track, codec_key) for the highest-priority English audio
    track in a probed file, or (None, None) if no English audio exists.
    """
    english_tracks = [t for t in result.audio_tracks if _is_english(t)]
    if not english_tracks:
        return None, None

    best_track = None
    best_key = None
    best_rank = None
    for track in english_tracks:
        key = classify_audio_track(track)
        rank = rank_of(key)
        if best_rank is None or rank < best_rank:
            best_track, best_key, best_rank = track, key, rank

    return best_track, best_key


def needs_processing(result: FileProbeResult) -> bool:
    """
    A file needs no processing only if it already has exactly one audio
    track and that track is English (per spec: 'if only one English audio
    track exists, keep it' -- with a single track there's nothing to strip).
    """
    if len(result.audio_tracks) != 1:
        return True
    return not _is_english(result.audio_tracks[0])
