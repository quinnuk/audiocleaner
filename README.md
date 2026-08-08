# 🎧 AudioCleaner

![Windows](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-BSD--2--Clause-green)

A minimal, "set it and forget it" Windows app that scans a folder of MKV files (recursively) and keeps only the single best English audio track per file — Dolby Atmos always wins when present — while never touching video, subtitles, chapters, fonts, attachments, or metadata.

[![Buy Me A Coffee](https://cdn.buymeacoffee.com/buttons/default-orange.png)](https://buymeacoffee.com/quinnuk)  
If AudioCleaner saves you disk space, a coffee is always appreciated ☕

---

## ✨ Key Features

- **Keeps exactly one, best-quality English audio track** per file — Atmos ➔ DTS:X ➔ TrueHD ➔ DTS-HD MA ➔ LPCM ➔ FLAC ➔ E-AC3 ➔ DTS ➔ AC3 ➔ AAC ➔ MP3
- **Zero quality loss** — remuxes only, never re-encodes video or audio
- **Never touches** subtitles, chapters, fonts, attachments, or metadata
- **Safe by design** — every file is rebuilt to a temp copy, verified, then atomically swapped in; if anything fails, the original is never touched
- **Watch Mode** — runs continuously in the background, auto-cleaning new files as Radarr/Sonarr drop them in
- **Multi-folder support** — monitor any number of folders across different drives at once
- **Starts with Windows**, minimised to the system tray

---

## 🚀 Getting Started

### Option 1: Pre-compiled EXE (recommended)

1. Download the latest `AudioCleaner.exe` from the **[Releases page](https://github.com/quinnuk/audiocleaner/releases/latest)**.
2. Run it — no Python installation needed.
3. Install [MKVToolNix](https://mkvtoolnix.download/) if you don't already have it (needed for `mkvmerge`). MediaInfo is bundled in, no separate install required.
4. Click **Add Folder…**, pick a library, and hit **Start**.

### Option 2: From Source

```bash
pip install -r requirements.txt
python main.py
```

Requirements for running from source:

- **Python 3.10+**
- **[MKVToolNix](https://mkvtoolnix.download/)** — provides `mkvmerge`. Must be on your `PATH`, or its executable placed in the project folder.
- **[MediaInfo](https://mediaarea.net/en/MediaInfo)** (CLI edition) — used alongside mkvmerge to reliably detect Atmos / DTS:X. Must be on your `PATH`, or its executable placed in the project folder.

Check both are installed and on PATH:

```cmd
mkvmerge --version
mediainfo --version
```

---

## 🖥️ How It Works

0. **Add your folders** — click "Add Folder…" once per movie/TV library. They can be on completely different drives with no shared parent — each is tracked independently, with its own cache and log file living inside that folder.
1. **Scan** — recursively finds every `.mkv` file under the selected folder. Metadata is probed (mkvmerge + mediainfo) and cached in `.audiocleaner_cache.json` in the root folder, so re-runs on an unchanged library are near-instant.
2. **Select** — for each file, ranks all English audio tracks by codec quality (Atmos+TrueHD ➔ DTS:X ➔ TrueHD ➔ DTS-HD MA ➔ LPCM ➔ FLAC ➔ E-AC3 ➔ DTS ➔ AC3 ➔ AAC ➔ MP3) and picks the best.
3. **Process** — files with only one audio track (already English) are left alone. Everything else is remuxed to a temp file (`name.ac_tmp.mkv`) containing only the chosen audio track — video is never re-encoded, and subtitles/chapters/fonts/attachments/metadata are preserved.
4. **Verify & replace** — the temp file is probed to confirm it has exactly one audio track in the expected language. Only then does it atomically replace the original. If verification fails, the temp file is discarded and the original is never touched.
5. **Log** — every decision is appended to `audiocleaner_log.txt` in the root folder, viewable via the "Open Log" button.

---

## 👁️ Watch Mode, System Tray & Autostart

Beyond a one-off scan, AudioCleaner can run continuously in the background and clean new files as they arrive — useful if it's paired with something like Radarr/Sonarr dropping files into your library.

- **Start Watching All Folders** — keeps a lightweight watcher running per folder that detects new/changed `.mkv` files, waits for them to finish copying (default 120s, matching typical Radarr/Sonarr move behaviour), then cleans them automatically.
- **System tray** — closing the window minimises to a tray icon instead of quitting, so watching continues in the background. Right-click the tray icon for Show Window, Start/Stop Watching, and Quit.
- **Start with Windows** — launches AudioCleaner automatically at login, minimised to the tray, and resumes watching your saved folders. Adds a per-user entry to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (no admin rights required).

---

## 🔨 Building a Standalone .exe

If you'd rather build it yourself than use the Release download:

```cmd
build.bat
```

This installs PyInstaller if needed, then builds. Your exe ends up at `dist\AudioCleaner.exe`.

Notes:
- Build **on Windows** — PyInstaller packages against the OS it runs on.
- First launch of a `--onefile` build is a bit slower (a second or two) since it unpacks itself into a temp folder each run — that's normal.
- mkvmerge still needs to be installed separately; the exe checks for it and shows a download prompt if missing.

---

## ⚠️ Codec Detection Caveat

Atmos and DTS:X are extensions layered on top of TrueHD/DTS, and are not always exposed cleanly by either tool alone. This app cross-references mkvmerge's codec string with mediainfo's commercial-name and additional-features fields. It's the standard practical approach, but on unusual/malformed files it's worth spot-checking the log the first time you run it against a new library.

---

## 📁 Project Layout

```
audiocleaner/
  config.py      codec priority list & constants
  probe.py       mkvmerge/mediainfo wrappers + on-disk cache
  codec_rank.py  codec classification & best-track selection
  processor.py   safe remux -> verify -> atomic replace
  scanner.py     recursive file discovery + pipeline orchestration
  watcher.py     folder watching for continuous/background cleaning
  worker.py      QThread wrapper (keeps GUI responsive)
  gui.py         PySide6 single-page interface
  autostart.py   Windows "start with Windows" (HKCU Run key) support
main.py          entry point
```

---

## ☕ Support This Project

AudioCleaner is free and built in my spare time. If it's useful to you, consider buying me a coffee — it's a big help and genuinely appreciated.

[![Buy Me A Coffee](https://cdn.buymeacoffee.com/buttons/default-orange.png)](https://buymeacoffee.com/quinnuk)