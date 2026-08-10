"""
Central configuration and constants for AudioCleaner.
"""

APP_NAME = "AudioCleaner"

# --- Cache / rules versioning ---
# Bump SCANNER_VERSION whenever probe.py's extraction logic changes in a way
# that could change what a cached FileProbeResult contains (new fields, new
# matching logic, etc). Bump RULES_VERSION whenever track-selection logic
# changes (codec_rank.py) in a way that could change *decisions* made from
# an unchanged probe result. Either bump invalidates old cache entries, so a
# stale cache never silently keeps applying pre-change decisions.
SCANNER_VERSION = "2"
RULES_VERSION = "2"

# --- Maximum Safety Mode ---
# When enabled, a full backup copy of the original is kept until *after* the
# post-replacement verification succeeds, and is used to restore the
# original if that final check fails. Off by default because the normal
# temp-file-then-verify-then-replace flow is already safe for the common
# case; this adds extra disk I/O and temporary space usage for users who
# want the additional guarantee against e.g. a corrupted replace.
DEFAULT_MAX_SAFETY_MODE = False
# If True, the backup is kept after a successful run instead of being
# deleted. Off by default -- most users don't want doubled disk usage
# building up across a whole library.
DEFAULT_PERSISTENT_BACKUP = False

# Ordered best -> worst. Keys are internal codec identifiers produced by
# codec_rank.classify_audio_track(). Lower index = higher priority.
CODEC_PRIORITY = [
    "truehd_atmos",   # Dolby TrueHD + Atmos
    "dtsx",            # DTS:X
    "truehd",          # Dolby TrueHD
    "dts_hd_ma",       # DTS-HD Master Audio
    "lpcm",            # LPCM
    "flac",            # FLAC
    "eac3",            # Dolby Digital Plus (E-AC3)
    "dts",             # DTS (core)
    "ac3",             # Dolby Digital (AC3)
    "aac",             # AAC
    "mp3",             # MP3
]

CODEC_RANK = {codec: i for i, codec in enumerate(CODEC_PRIORITY)}

# Human-readable labels for logs / UI.
CODEC_LABELS = {
    "truehd_atmos": "Dolby TrueHD + Atmos",
    "dtsx": "DTS:X",
    "truehd": "Dolby TrueHD",
    "dts_hd_ma": "DTS-HD Master Audio",
    "lpcm": "LPCM",
    "flac": "FLAC",
    "eac3": "Dolby Digital Plus (E-AC3)",
    "dts": "DTS",
    "ac3": "Dolby Digital (AC3)",
    "aac": "AAC",
    "mp3": "MP3",
    "unknown": "Unknown",
}

# English language tags as they appear in MKV/mkvmerge/mediainfo output.
ENGLISH_LANG_CODES = {"eng", "en", "en-us", "en-gb"}

# --- Commentary tracks ---
# Off by default: commentary tracks are treated like any other extra audio
# track and stripped. When on, the single best non-commentary track is
# still chosen as "the" kept track, but commentary track(s) are kept
# alongside it rather than being removed.
DEFAULT_KEEP_COMMENTARY = False

# --- Subtitle language filtering ---
# Off by default, so existing behaviour (subtitles are never touched) is
# unchanged unless a user explicitly opts in. When on, only subtitle
# tracks matching a language in DEFAULT_SUBTITLE_LANGUAGES are kept,
# *plus* any track flagged Forced regardless of language (these are
# usually foreign-dialogue captions within an otherwise-English film that
# people expect kept even when everything else in that language is
# stripped).
DEFAULT_SUBTITLE_FILTER_ENABLED = False
DEFAULT_SUBTITLE_LANGUAGES = {"eng"}

# Cache file name written into the target root folder.
CACHE_FILENAME = ".audiocleaner_cache.json"

# Log file name written into the target root folder.
LOG_FILENAME = "audiocleaner_log.txt"

MKV_EXTENSIONS = {".mkv"}

# --- Watch mode ---
# How often the watcher re-scans the folder tree for new/changed files.
WATCH_POLL_INTERVAL_SECONDS = 15

# How long a file's size must stay unchanged before it's considered fully
# copied and safe to process. User-adjustable in the GUI; this is just the
# default (matches the "wait a minute or two" guidance for Radarr/Sonarr
# moving files into the library folder).
WATCH_DEFAULT_SETTLE_SECONDS = 120
