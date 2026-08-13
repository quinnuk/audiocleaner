"""
Classifies an AudioTrackInfo into one of the internal codec keys defined in
config.CODEC_PRIORITY, and selects the best English track for a file.

Atmos and DTS:X are extensions layered on top of a core codec (TrueHD / DTS)
and are not always reported by mkvmerge, so we prefer mediainfo's commercial
name / additional-features fields when available, and fall back to
mkvmerge's codec_name string (recent MKVToolNix versions do append
"Atmos" to TrueHD tracks it detects).
"""

from dataclasses import dataclass
from typing import Optional

from .config import ENGLISH_LANG_CODES, CODEC_RANK, CODEC_LABELS
from .probe import AudioTrackInfo, FileProbeResult


def _is_preferred_language(track: AudioTrackInfo, languages) -> bool:
    return track.language.lower() in languages


def _is_english(track: AudioTrackInfo) -> bool:
    """Back-compat wrapper: English only. Prefer _is_preferred_language
    with an explicit language set for new code."""
    return _is_preferred_language(track, ENGLISH_LANG_CODES)


def is_commentary(track: AudioTrackInfo) -> bool:
    """True if a track is a commentary track. Trusts mkvmerge's own
    flag_commentary property when present; probe.py already falls back to
    a name-text check ("commentary" in the track title) for files that
    never set the flag, so this just reads what probe.py already decided."""
    return bool(getattr(track, "commentary", False))


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


def select_audio_tracks_to_keep(
    result: FileProbeResult,
    keep_commentary: bool = False,
    preferred_languages: Optional[set] = None,
) -> tuple[Optional[AudioTrackInfo], Optional[str], list]:
    """
    Returns (best_track, codec_key, extra_tracks):
      - best_track / codec_key: the single highest-priority track in one of
        preferred_languages (English only by default -- pass an explicit
        set, e.g. {"eng", "jpn"}, to keep a different language or several),
        chosen from non-commentary tracks whenever any exist (so a
        commentary track never accidentally becomes "the" kept track,
        regardless of the keep_commentary setting).
      - extra_tracks: additional matching-language commentary track(s) to
        keep alongside best_track. Empty unless keep_commentary is True.
    Returns (None, None, []) if no track in preferred_languages exists.
    """
    languages = {l.lower() for l in preferred_languages} if preferred_languages else ENGLISH_LANG_CODES
    english_tracks = [t for t in result.audio_tracks if _is_preferred_language(t, languages)]
    if not english_tracks:
        return None, None, []

    non_commentary = [t for t in english_tracks if not is_commentary(t)]
    commentary_tracks = [t for t in english_tracks if is_commentary(t)]

    # Rank among non-commentary tracks normally; only fall back to ranking
    # commentary tracks if that's genuinely all the English audio a file has.
    candidates = non_commentary or english_tracks

    best_track = None
    best_key = None
    best_rank = None
    for track in candidates:
        key = classify_audio_track(track)
        rank = rank_of(key)
        if best_rank is None or rank < best_rank:
            best_track, best_key, best_rank = track, key, rank

    extra_tracks = []
    if keep_commentary and best_track is not None:
        extra_tracks = [t for t in commentary_tracks if t.track_id != best_track.track_id]

    return best_track, best_key, extra_tracks


def select_best_english_track(
    result: FileProbeResult,
) -> tuple[Optional[AudioTrackInfo], Optional[str]]:
    """Back-compat wrapper: best track only, no commentary handling."""
    best_track, best_key, _ = select_audio_tracks_to_keep(result, keep_commentary=False)
    return best_track, best_key


def track_label(track: AudioTrackInfo, codec_key: Optional[str] = None) -> str:
    """Human-readable label for a track, e.g. 'English — Dolby TrueHD + Atmos 7.1'."""
    key = codec_key or classify_audio_track(track)
    lang = (track.language or "und").upper()
    lang_names = {"ENG": "English", "FRE": "French", "FRA": "French", "GER": "German",
                  "DEU": "German", "SPA": "Spanish", "UND": "Unknown language"}
    lang_display = lang_names.get(lang, lang)
    codec_display = CODEC_LABELS.get(key, key or "Unknown")
    channel_display = f" {track.channels}ch" if track.channels else ""
    return f"{lang_display} — {codec_display}{channel_display}"


@dataclass
class AudioTrackDecision:
    track_id: int
    kept: bool
    label: str
    reason: str
    commentary: bool = False


def explain_audio_selection(
    result: FileProbeResult,
    keep_commentary: bool = False,
    preferred_languages: Optional[set] = None,
) -> list:
    """Per-track KEEP/REMOVE decisions with a human-readable reason for
    each, built from exactly the same selection this module's
    select_audio_tracks_to_keep() would make -- so the explanation can
    never drift out of sync with the actual behaviour (spec sec 15)."""
    languages = {l.lower() for l in preferred_languages} if preferred_languages else ENGLISH_LANG_CODES
    best_track, best_key, extra_tracks = select_audio_tracks_to_keep(
        result, keep_commentary=keep_commentary, preferred_languages=languages
    )
    keep_ids = set()
    if best_track is not None:
        keep_ids.add(best_track.track_id)
    keep_ids |= {t.track_id for t in extra_tracks}
    best_label = track_label(best_track, best_key) if best_track is not None else None

    decisions = []
    for track in result.audio_tracks:
        key = classify_audio_track(track)
        label = track_label(track, key)
        commentary = is_commentary(track)
        kept = track.track_id in keep_ids

        if kept:
            if best_track is not None and track.track_id == best_track.track_id:
                if commentary:
                    reason = "Highest-ranked English audio track (only commentary tracks were available)."
                else:
                    reason = "Highest-ranked English non-commentary audio track."
            else:
                reason = "Commentary track kept in addition to the primary track because 'Keep commentary' is enabled."
        else:
            if not _is_preferred_language(track, languages):
                if preferred_languages is None:
                    # Back-compat wording for the default (English-only) case.
                    reason = f"Not an English track (language: {track.language or 'und'})."
                else:
                    reason = f"Not a preferred-language track (language: {track.language or 'und'})."
            elif commentary and not keep_commentary:
                reason = "Commentary track removed ('Keep commentary' is off)."
            elif best_label is not None:
                reason = f"Lower priority than the selected {best_label} track."
            else:
                reason = "Not selected."

        decisions.append(AudioTrackDecision(
            track_id=track.track_id, kept=kept, label=label, reason=reason, commentary=commentary,
        ))
    return decisions


def select_subtitle_tracks_to_keep(
    result: FileProbeResult,
    keep_languages,
) -> list:
    """
    Subtitle tracks to keep when subtitle filtering is enabled: any track
    whose language is in keep_languages, plus any track flagged Forced
    regardless of language (these are usually foreign-dialogue captions
    within an otherwise-English film, expected to stay even when
    everything else in that language gets stripped).
    """
    langs = {l.lower() for l in (keep_languages or ())}
    return [t for t in result.subtitle_tracks if t.forced or t.language.lower() in langs]


@dataclass
class SubtitleTrackDecision:
    track_id: int
    kept: bool
    label: str
    reason: str


def explain_subtitle_selection(result: FileProbeResult, keep_languages) -> list:
    """Per-track KEEP/REMOVE explanation for subtitles, mirroring
    explain_audio_selection (spec sec 15). Only meaningful when subtitle
    filtering is enabled -- callers should not call this (and should just
    report 'unchanged') when filtering is off."""
    keep_ids = {t.track_id for t in select_subtitle_tracks_to_keep(result, keep_languages)}
    decisions = []
    for track in result.subtitle_tracks:
        lang = (track.language or "und").upper()
        label = f"{lang} subtitles" + (" (forced)" if track.forced else "")
        kept = track.track_id in keep_ids
        if kept:
            reason = "Forced track, kept regardless of language filter." if track.forced else "Language selected to keep."
        else:
            reason = f"Language '{track.language}' not in the selected keep-list."
        decisions.append(SubtitleTrackDecision(track_id=track.track_id, kept=kept, label=label, reason=reason))
    return decisions


def needs_processing(
    result: FileProbeResult,
    keep_commentary: bool = False,
    subtitle_filter_enabled: bool = False,
    subtitle_languages=None,
    preferred_languages: Optional[set] = None,
) -> bool:
    """
    A file needs processing if the audio tracks that would be kept differ
    from what's already on disk, or (when subtitle filtering is enabled)
    if the subtitle tracks that would be kept differ from what's on disk.
    """
    best_track, _key, extra_tracks = select_audio_tracks_to_keep(
        result, keep_commentary=keep_commentary, preferred_languages=preferred_languages
    )
    if best_track is None:
        return True  # no English audio at all - report as an error case upstream

    keep_ids = {best_track.track_id} | {t.track_id for t in extra_tracks}
    original_ids = {t.track_id for t in result.audio_tracks}
    if keep_ids != original_ids:
        return True

    if subtitle_filter_enabled and result.subtitle_tracks:
        kept_subs = select_subtitle_tracks_to_keep(result, subtitle_languages or set())
        if {t.track_id for t in kept_subs} != {t.track_id for t in result.subtitle_tracks}:
            return True

    return False
