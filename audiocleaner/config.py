"""
Central configuration and constants for AudioCleaner.
"""

APP_NAME = "AudioCleaner"

# --- Cache / rules versioning ---
# Bump SCANNER_VERSION whenever probe.py's extraction logic changes in a way
# that could change what a cached FileProbeResult contains (new fields, new
# matching logic, etc). This is the version ProbeCache uses to invalidate
# stale probe data. RULES_VERSION identifies track-selection rules and can be
# recorded by callers/history when decision semantics change; changing it does
# not invalidate probe data because codec-ranking changes do not alter the
# underlying MediaInfo/mkvmerge facts stored in the cache.
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
    "truehd_atmos",
    "dtsx",
    "truehd",
    "dts_hd_ma",
    "lpcm",
    "flac",
    "eac3",
    "dts",
    "ac3",
    "aac",
    "mp3",
]

CODEC_RANK = {codec: i for i, codec in enumerate(CODEC_PRIORITY)}

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

ENGLISH_LANG_CODES = {"eng", "en", "en-us", "en-gb"}

DEFAULT_KEEP_COMMENTARY = False
DEFAULT_SUBTITLE_FILTER_ENABLED = False
DEFAULT_SUBTITLE_LANGUAGES = {"eng"}

CACHE_FILENAME = ".audiocleaner_cache.json"
LOG_FILENAME = "audiocleaner_log.txt"
MKV_EXTENSIONS = {".mkv"}

WATCH_POLL_INTERVAL_SECONDS = 15
WATCH_DEFAULT_SETTLE_SECONDS = 120
