"""
Builds the synthetic MKV fixtures under tests/fixtures/ from scratch using
ffmpeg + mkvmerge. Nothing here depends on any copyrighted movie or show --
every fixture is a few seconds of generated colour bars and sine-wave tones,
which is all the processing pipeline needs to see (it never looks at pixel
or waveform content, only container-level track metadata).

Run this manually to regenerate fixtures after changing what they cover:

    python3 tests/fixtures/build_fixtures.py

Requires ffmpeg, mkvmerge, and mediainfo on PATH (same tools AudioCleaner
itself depends on). Not run automatically as part of the test suite --
the fixtures are checked into the repo so `pytest` doesn't need these
tools' encoders (only mkvmerge/mediainfo, which are already required to
run AudioCleaner at all) unless someone wants to rebuild them.

Fixtures produced:
  multi_track.mkv    - video + 5 audio tracks (Eng AC3, Eng DTS, Eng TrueHD,
                        Fre AC3, Eng AC3-commentary) + 2 subtitle tracks
                        (Eng, Fre-forced). Exercises codec ranking,
                        commentary detection, and track matching together.
  no_english.mkv      - video + French/German audio only. No English track
                        exists -> must be skipped (spec sec 11).
  single_track.mkv    - video + one English AC3 track already. Nothing to
                        remove -> must be reported as already-clean, not
                        touched.
  unknown_codec.mkv   - video + one English Opus track. Opus isn't in
                        AudioCleaner's codec map -> must be skipped as
                        unrecognised, never guessed at (spec sec 8).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def _require(tool: str):
    if shutil.which(tool) is None:
        sys.exit(f"'{tool}' not found on PATH -- install it before running this script.")


def build(tmp: Path):
    def run(cmd):
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    video = tmp / "video_only.mkv"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=blue:s=320x240:d=2", "-c:v", "libx264", "-an", str(video)])

    def tone(name, freq, codec, extra=None):
        out = tmp / name
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
               "-i", f"sine=frequency={freq}:duration=2", "-c:a", codec, "-ac", "6"]
        if extra:
            cmd += extra
        cmd.append(str(out))
        run(cmd)
        return out

    eng_ac3 = tone("eng_ac3.ac3", 440, "ac3")
    eng_dts = tone("eng_dts.dts", 550, "dca", extra=["-strict", "-2"])
    eng_truehd = tone("eng_truehd.thd", 880, "truehd", extra=["-strict", "-2"])
    fra_ac3 = tone("fra_ac3.ac3", 660, "ac3")
    eng_commentary = tone("eng_commentary.ac3", 770, "ac3")
    deu_ac3 = tone("deu_ac3.ac3", 330, "ac3")
    eng_opus_raw = tmp / "eng_opus.opus"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=990:duration=2", "-c:a", "libopus", str(eng_opus_raw)])

    eng_srt = tmp / "eng.srt"
    eng_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello world.\n")
    fra_srt = tmp / "fra.srt"
    fra_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nBonjour le monde.\n")

    def mkvmerge(out_name, args):
        run(["mkvmerge", "-o", str(FIXTURES_DIR / out_name)] + args)

    mkvmerge("multi_track.mkv", [
        "--language", "0:und", str(video),
        "--language", "0:eng", str(eng_ac3),
        "--language", "0:eng", str(eng_dts),
        "--language", "0:eng", "--track-name", "0:Dolby TrueHD", str(eng_truehd),
        "--language", "0:fra", str(fra_ac3),
        "--language", "0:eng", "--commentary-flag", "0:yes",
        "--track-name", "0:Director Commentary", str(eng_commentary),
        "--language", "0:eng", str(eng_srt),
        "--language", "0:fra", "--forced-display-flag", "0:yes", str(fra_srt),
    ])

    mkvmerge("no_english.mkv", [
        "--language", "0:und", str(video),
        "--language", "0:fra", str(fra_ac3),
        "--language", "0:deu", str(deu_ac3),
    ])

    mkvmerge("single_track.mkv", [
        "--language", "0:und", str(video),
        "--language", "0:eng", str(eng_ac3),
    ])

    mkvmerge("unknown_codec.mkv", [
        "--language", "0:und", str(video),
        "--language", "0:eng", str(eng_opus_raw),
    ])


if __name__ == "__main__":
    _require("ffmpeg")
    _require("mkvmerge")
    with tempfile.TemporaryDirectory() as tmp:
        build(Path(tmp))
    print(f"Fixtures written to {FIXTURES_DIR}")
