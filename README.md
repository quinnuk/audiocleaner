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

**Atmos → DTS:X → TrueHD → DTS-HD MA → LPCM → FLAC → E-AC3 → DTS → AC3 → AAC → MP3**

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
 Analyse tracks
     │
     ▼
 Select best English track
     │
     ▼
 Create temporary MKV
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
                    Replace original
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
- **[MKVToolNix](https://mkvtoolnix.download/)** — provides `mkvmerge`. It must be on your `PATH`, or its executable must be placed in the project directory.
- **[MediaInfo](https://mediaarea.net/en/MediaInfo)** (CLI edition) — used alongside `mkvmerge` to reliably detect Atmos / DTS:X. It must be on your `PATH`, or its executable must be placed in the project directory.

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

Folders can be located on completely different drives and do not need to share a common parent directory. Each folder is tracked independently, with its own cache and log file.

### 2. 🔍 Scan

AudioCleaner recursively finds every `.mkv` file under the selected folders.

Metadata is probed using `mkvmerge` and MediaInfo and cached in:

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

The temporary file contains only the chosen audio track while preserving the video, subtitles, chapters, fonts, attachments, and metadata.

**Nothing is re-encoded.**

### 5. ✅ Verify & Replace

The temporary file is probed to confirm that it contains exactly one audio track in the expected language.

Only after verification succeeds does AudioCleaner atomically replace the original.

If verification fails, the temporary file is discarded and the original is never touched.

### 6. 📋 Log

Every decision is appended to:

```text
audiocleaner_log.txt
```

The log can be opened directly from the application using **Open Log**.

---

## 👁️ Watch Mode

AudioCleaner can run continuously in the background and automatically clean new files as they arrive.

This is particularly useful alongside applications such as **Radarr** and **Sonarr**.

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

- **Start Watching All Folders** — runs a lightweight watcher for each configured folder.
- Detects new or changed `.mkv` files.
- Waits for files to finish copying before processing.
- Automatically cleans new files.
- Continues running in the background.

The default file-stability wait is **120 seconds**, matching typical Radarr/Sonarr move behaviour.

---

## 🖥️ System Tray

Closing the AudioCleaner window minimises it to the Windows system tray instead of quitting, allowing Watch Mode to continue running in the background.

Right-click the tray icon to access:

- **Show Window**
- **Start Watching**
- **Stop Watching**
- **Quit**

---

## 🚀 Start with Windows

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

No administrator rights are required.

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

```cmd
build.bat
```

The build script installs PyInstaller if needed and creates:

```text
dist\AudioCleaner.exe
```

### Build Notes

- Build **on Windows** — PyInstaller packages against the operating system it runs on.
- The first launch of a `--onefile` build may be slightly slower because it extracts itself into a temporary directory.
- `mkvmerge` still needs to be installed separately.
- The executable checks for `mkvmerge` and shows a download prompt if it is missing.

---

## 📁 Project Structure

```text
audiocleaner/
├── config.py       # Codec priority list & constants
├── probe.py        # mkvmerge/MediaInfo wrappers & on-disk cache
├── codec_rank.py   # Codec classification & best-track selection
├── processor.py    # Safe remux → verify → atomic replace
├── scanner.py      # Recursive file discovery & pipeline orchestration
├── watcher.py      # Folder watching for continuous/background cleaning
├── worker.py       # QThread wrapper to keep the GUI responsive
├── gui.py          # PySide6 single-page interface
├── autostart.py    # Windows "Start with Windows" support
└── main.py         # Application entry point
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

## ☕ Support This Project

AudioCleaner is free and built in my spare time.

If it saves you disk space or makes managing your media library easier, consider buying me a coffee — it's a big help and genuinely appreciated.

<p align="center">
  <a href="https://buymeacoffee.com/quinnuk">
    <img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee">
  </a>
</p>

---

## 📄 License

AudioCleaner is released under the **BSD 2-Clause License**.

See the repository for the full license text.
