# 🎧 AudioCleaner

<p align="center">
  <strong>Automatically keep the best English audio track in your MKV library.</strong>
</p>

<p align="center">
  A lightweight Windows utility that safely removes unwanted audio tracks without re-encoding your media.
</p>

<p align="center">
  <a href="https://github.com/quinnuk/audiocleaner/releases/latest">
    <img src="https://img.shields.io/github/v/release/quinnuk/audiocleaner?style=for-the-badge" alt="Latest Release">
  </a>
  <img src="https://img.shields.io/badge/platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-BSD--2--Clause-green?style=for-the-badge" alt="License">
</p>
<p align="center">
  <a href="https://buymeacoffee.com/quinnuk" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="60" width="217">
  </a>
  <br>
  <sub>If AudioCleaner saves you disk space, a coffee is always appreciated ☕</sub>
</p>
<p align="center">
  <img src="screenshot.jpg" alt="AudioCleaner application screenshot" width="900">
</p>

---

## ✨ What is AudioCleaner?

AudioCleaner is a simple, **"set it and forget it" Windows application** that recursively scans your MKV library and keeps exactly one best-quality English audio track per file.

It is designed to be safe and hands-off:

**Point it at your library → Start it → Let it do the work.**

Dolby Atmos always wins when present, and AudioCleaner never re-encodes your media.

### 🔊 Audio Quality Priority

English audio tracks are ranked in this order:

**Atmos + TrueHD → DTS:X → TrueHD → DTS-HD MA → LPCM → FLAC → E-AC3 → DTS → AC3 → AAC → MP3**

---

## 🛡️ Safe by Design

AudioCleaner is deliberately conservative when modifying your media.

It **only remuxes** files — video and audio are never re-encoded, so there is no quality loss.

The following are preserved:

- 🎬 Video
- 💬 Subtitles
- 📖 Chapters
- 🔤 Fonts
- 📎 Attachments
- 🏷️ Metadata

Every file follows a safe temporary-file workflow:

```text
Original MKV
     │
     ▼
 Analyse tracks (mkvmerge + MediaInfo, run in parallel)
     │
     ▼
 Select best English track
     │
     ▼
 Create temporary MKV (name.ac_tmp.mkv)
     │
     ▼
 Verify result
     │
     ├─────────────── ❌ Failed
     │                    │
     │                    ▼
     │              Delete temp file
     │              Keep original
     │
     └─────────────── ✅ Passed
                          │
                          ▼
              Atomically replace original (os.replace)
```

The original file is **never replaced until the new file has been successfully created and verified**.

If anything fails, the original remains untouched.

---

## ✨ Key Features

| | Feature | Description |
|---|---|---|
| 🎯 | **Smart Track Selection** | Keeps exactly one, best-quality English audio track |
| 🔊 | **Atmos Priority** | Dolby Atmos is preferred whenever available |
| ⚡ | **Zero Quality Loss** | Remuxes only — never re-encodes video or audio |
| 🛡️ | **Safe Processing** | Builds, verifies, and then atomically replaces the original |
| 👁️ | **Watch Mode** | Automatically processes new MKVs as they arrive |
| 📁 | **Multiple Folders** | Monitor libraries across different drives at once |
| 💾 | **Smart Caching** | Caches metadata so unchanged libraries scan quickly |
| 🖥️ | **System Tray** | Runs quietly in the background |
| 🚀 | **Windows Startup** | Automatically starts and resumes watching at login |
| 📋 | **Detailed Logging** | Records every processing decision |

---

## 📸 Screenshot

<p align="center">
  <img src="screenshot.jpg" alt="AudioCleaner interface" width="900">
</p>

---

## 🚀 Getting Started

### 📦 Option 1 — Pre-compiled EXE

**[⬇️ Download the latest release](https://github.com/quinnuk/audiocleaner/releases/latest)**

1. Download `AudioCleaner.exe`.
2. Run it — **no Python installation is required**.
3. Install [MKVToolNix](https://mkvtoolnix.download/) if you don't already have it.
4. Click **Add Folder…**.
5. Select your movie or TV library.
6. Click **Start**.

> **Note:** MKVToolNix is required because AudioCleaner uses `mkvmerge` to safely remux MKV files. MediaInfo is bundled with the application.

---

### 🐍 Option 2 — Run from Source

Install the required Python packages:

```bash
pip install -r requirements.txt
```

Then launch AudioCleaner:

```bash
python main.py
```

### Requirements

- **Windows**
- **Python 3.10+**
- **[MKVToolNix](https://mkvtoolnix.download/)** — provides `mkvmerge`. Must be on your `PATH`, or its executable placed in the project directory (or next to `AudioCleaner.exe`).
- **[MediaInfo](https://mediaarea.net/en/MediaInfo)** (CLI edition) — used alongside `mkvmerge` to reliably detect Atmos / DTS:X. Must be on your `PATH`, or its executable placed in the project directory (or next to `AudioCleaner.exe`).

If you're running the standalone `.exe`, keeping `MediaInfo.exe` directly next to `AudioCleaner.exe` is the simplest option and avoids a system-wide install.

Check both are installed correctly:

```cmd
mkvmerge --version
mediainfo --version
```

---

## 🖥️ How It Works

AudioCleaner follows a simple and safe processing pipeline.

### 1. 📁 Add Your Folders

Click **Add Folder…** once for each movie or TV library.

Folders can be located on completely different drives and do not need to share a common parent directory. Each folder is tracked independently, with its own cache and log file living inside that folder.

### 2. 🔍 Scan

AudioCleaner recursively finds every `.mkv` file under the selected folders.

Metadata is probed in parallel using `mkvmerge` and MediaInfo, and cached in:

```text
.audiocleaner_cache.json
```

Re-running AudioCleaner on an unchanged library can therefore be near-instant.

### 3. 🎯 Select

For each file, AudioCleaner ranks all English audio tracks by codec quality:

```text
Atmos + TrueHD
      ↓
DTS:X
      ↓
TrueHD
      ↓
DTS-HD MA
      ↓
LPCM
      ↓
FLAC
      ↓
E-AC3
      ↓
DTS
      ↓
AC3
      ↓
AAC
      ↓
MP3
```

The highest-ranked English track is selected.

### 4. 🔨 Process

Files with only one audio track that is already English are left alone.

Everything else is remuxed to a temporary file:

```text
name.ac_tmp.mkv
```

The temporary file contains only the chosen audio track while preserving the video, subtitles, chapters, fonts, attachments, and metadata (mkvmerge's default behaviour).

**Nothing is re-encoded.**

### 5. ✅ Verify & Replace

The temporary file is probed to confirm that it contains exactly one audio track in the expected language.

Only after verification succeeds does AudioCleaner atomically replace the original (`os.replace`).

If verification fails, the temporary file is discarded and the original is never touched.

### 6. 📋 Log

Every decision is appended to:

```text
audiocleaner_log.txt
```

The log can be opened directly from the application using **Open Log**.

---

## 👁️ Watch Mode, System Tray & Autostart

Beyond a one-off scan, AudioCleaner can run continuously in the background and clean new files as they arrive — particularly useful alongside applications such as **Radarr** and **Sonarr**.

```text
┌────────────────┐
│  Radarr/Sonarr │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│   New MKV      │
│    arrives     │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ AudioCleaner   │
│    detects     │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ Wait for file  │
│ to finish      │
│ copying        │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ Find the best  │
│ English track  │
└───────┬────────┘
        │
        ▼
┌────────────────┐
│ Safely remux   │
│ and verify     │
└───────┬────────┘
        │
        ▼
       ✅ Done
```

### Watch Mode Features

- **Start Watching All Folders** — runs a lightweight watcher for each configured folder, using the same select → process → verify → replace pipeline as a manual run.
- Detects new or changed `.mkv` files.
- Waits for files to finish copying before processing — configurable via the "Wait for new files to finish copying" setting, **default 120 seconds**, matching typical Radarr/Sonarr move behaviour.
- Continues running in the background.

### System Tray

Closing the AudioCleaner window minimises it to the Windows system tray instead of quitting, allowing Watch Mode to continue running in the background.

Right-click the tray icon to access:

- **Show Window**
- **Start Watching**
- **Stop Watching**
- **Quit**

Quit is the only way to fully exit while watching.

### Start with Windows

AudioCleaner can optionally launch automatically when you sign into Windows.

When enabled, it:

1. Starts automatically at login.
2. Launches minimised to the system tray.
3. Restores your saved folders.
4. Resumes watching automatically.

AudioCleaner adds a per-user entry to:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

No administrator rights are required, and unticking the option removes the entry. Your folder list and the "wait for new files" setting are remembered between sessions either way.

---

## 💾 Smart Caching

Large media libraries can contain thousands of files.

AudioCleaner caches probed metadata in:

```text
.audiocleaner_cache.json
```

This allows unchanged files to be skipped on subsequent scans, making repeated scans of an established library much faster.

---

## ⚠️ Codec Detection Caveat

Atmos and DTS:X are extensions layered on top of TrueHD and DTS, and they are not always exposed cleanly by either tool alone.

AudioCleaner cross-references `mkvmerge`'s codec string with MediaInfo's commercial-name and additional-features fields to identify these formats.

This is a practical approach for real-world media files, but unusual or malformed files may occasionally be detected unexpectedly.

For a new library, it is worth spot-checking the log after the first scan.

---

## 🔨 Building a Standalone `.exe`

If you'd rather build AudioCleaner yourself instead of using the release download:

1. Make sure `pip install -r requirements.txt` has already been run.
2. Double-click **`build.bat`** in this folder (or run it from a Command Prompt).
3. It installs PyInstaller if needed, then builds. When it finishes, your exe is at `dist\AudioCleaner.exe` — copy that one file anywhere you like and run it directly. No Python installation is needed on the machine you copy it to.

### Build Notes

- Build **on Windows** — PyInstaller packages against the operating system it runs on.
- The first launch of a `--onefile` build may be slightly slower because it extracts itself into a temporary directory.
- `mkvmerge` still needs to be installed separately.
- The executable checks for `mkvmerge` and shows a download prompt if it is missing.
- Rebuilding: just re-run `build.bat` any time you get updated source files — it overwrites the previous `dist\AudioCleaner.exe`.

---

## 📁 Project Structure

```text
audiocleaner/
├── config.py       # Codec priority list & constants
├── probe.py        # mkvmerge/MediaInfo wrappers & on-disk cache
├── codec_rank.py   # Codec classification & best-track selection
├── processor.py    # Safe remux → verify → atomic replace
├── scanner.py       # Recursive file discovery & pipeline orchestration
├── watcher.py       # Folder watching for continuous/background cleaning
├── worker.py        # QThread wrapper to keep the GUI responsive
├── gui.py           # PySide6 single-page interface
├── autostart.py     # Windows "Start with Windows" support
└── main.py          # Application entry point
```

---

## 🧰 External Dependencies

### MKVToolNix

AudioCleaner uses `mkvmerge` for safe MKV remuxing.

**[Download MKVToolNix](https://mkvtoolnix.download/)**

### MediaInfo

AudioCleaner uses MediaInfo alongside `mkvmerge` to reliably detect formats such as Dolby Atmos and DTS:X.

**[Download MediaInfo](https://mediaarea.net/en/MediaInfo)**

> MediaInfo is bundled with the pre-compiled AudioCleaner release. A separate installation is only required when running from source, unless you provide the executable in the project directory.

---

## 🧪 Development & Testing

AudioCleaner has an automated test suite under `tests/`, run in CI on every push via GitHub Actions (`.github/workflows/tests.yml`).

```
pip install -r requirements.txt
pip install pytest
pytest tests/
```

Most tests run with mocked probe data and need nothing beyond Python + pytest. A smaller set of integration tests (`tests/test_integration_fixtures.py`) exercises the real `mkvmerge`/`mediainfo` pipeline against synthetic test files in `tests/fixtures/` — these are skipped automatically if those tools aren't on your `PATH`.

The fixtures themselves are generated (not copyrighted media) from a short colour-bar clip and sine-wave tones. To rebuild them after changing what they cover:

```
python3 tests/fixtures/build_fixtures.py
```

(requires `ffmpeg` and `mkvmerge` on `PATH`).

---

## ☕ Support This Project

AudioCleaner is free and built in my spare time — if it's useful to you, consider buying me a coffee.

<p align="center">
  <a href="https://buymeacoffee.com/quinnuk">
    <img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee">
  </a>
</p>

---

## 📄 License

AudioCleaner is released under the **BSD 2-Clause License**.

See the repository for the full license text.
