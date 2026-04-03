# Bulk Video Compressor

A lightweight macOS desktop app that batch-compresses video files using ffmpeg. Scan a folder, review the detected settings, and let it encode — all with a clean progress UI.

Built for people who want to compress a library of movies quickly without manually adding files to HandBrake one by one. Feed it a folder full of subdirectories and walk away.

![Python](https://img.shields.io/badge/python-3.11+-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-green) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)

---

## Author

Made with 💛 by **[Paul Davies](https://github.com/DavoInMelbourne)**

**Like this project?** Help keep the lights on at [weluvbeer.com](https://www.weluvbeer.com) by buying me a Ko-fi!

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/weluvbeer)

---

## Features

- 📂 Recursively scans a source folder for video files across any number of subdirectories
- 🔍 Auto-detects resolution, FPS, audio tracks and subtitles per file
- 🎬 Review all files before encoding — see exactly what will be processed
- ⚙️ **Encoding presets** — choose speed/quality trade-off:
  - **Fast H.264** — x264, fast preset, RF 22 (closest to HandBrake's Fast preset)
  - **Balanced H.265** — x265, medium preset, RF 20 (default — good compression, reasonable speed)
  - **Quality H.265 12-bit** — x265 12-bit, medium preset, RF 20 (best compression, slowest)
- 🔊 Audio **bitexact stream copy** — the original audio is copied byte-for-byte, preserving codec, channels, channel layout and bitrate (AAC 5.1, AC3, DTS, TrueHD, FLAC etc.)
- 🌍 English or Foreign audio track preference
- 📝 Subtitles passed through (Forced → Regular → SDH), never burned in
- 📁 Mirrors source folder structure in the output directory
- 📄 Copies non-video files (subtitles, artwork, NFO etc.) on a per-directory basis, just before each directory is encoded — nothing is created upfront
- ✅ **Post-encode verification** — ffprobe checks every output file's duration against the source. Each row shows **✓ Safe to delete** (green) or **⚠ KEEP ORIGINAL** (red) so you know exactly which originals are safe to remove
- 📊 Scrollable per-file progress panel with FPS and ETA — handles large libraries without the UI locking up
- ❌ Cancel individual files or stop everything immediately
- 🧹 Dismiss completed rows individually or clear all finished files with one click
- ➕ Add more files to the queue while encoding is already running

---

## Prerequisites

### 1. Python 3.11+

```bash
python3 --version
```

If needed, install via [python.org](https://www.python.org/downloads/) or Homebrew:

```bash
brew install python
```

---

### 2. ffmpeg

Movie Compressor uses ffmpeg as its encoding engine. Install via Homebrew:

```bash
brew install ffmpeg
```

> Don't have Homebrew? Install it from [brew.sh](https://brew.sh).

Verify it works:

```bash
ffmpeg -version
ffprobe -version
```

The app auto-detects ffmpeg at the standard Homebrew locations. If you install it elsewhere, set the path manually in the app.

---

### 3. MediaInfo (recommended)

Used to read video/audio/subtitle track info from your files:

```bash
brew install mediainfo
```

> If MediaInfo is not available, the app falls back to ffprobe automatically.

---

## Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/movie-compressor.git
cd movie-compressor

# Install Python dependencies
pip install -r requirements.txt

# Run
python main.py
```

> **Tip:** Use a virtual environment:
>
> ```bash
> python3 -m venv venv
> source venv/bin/activate
> pip install -r requirements.txt
> python main.py
> ```

---

## Usage

1. **Source Directory** — folder to scan (scanned recursively including all subdirectories)
2. **Output Directory** — where encoded files are written, mirroring the source structure
3. **Preset** — select encoding speed/quality trade-off
4. **Audio Language** — prefer English or Foreign track
5. **RF Quality** — Constant Quality value (set automatically by preset; lower = better quality / larger file)
6. **ffmpeg Path** — auto-detected; override if needed
7. Click **Scan & Review** — inspect every file's detected settings before committing
8. Click **Add to Queue** to start encoding
9. Each file shows a coloured status badge throughout processing:

| Badge            | Colour | Meaning                                    |
| ---------------- | ------ | ------------------------------------------ |
| Waiting          | Grey   | Queued, not yet started                    |
| Encoding         | Blue   | Currently being encoded                    |
| Scanning…        | Orange | Audio packet scan in progress              |
| ✓ Safe to delete | Green  | Verified — original can be removed         |
| ⚠ Keep original  | Red    | Verification failed — do not delete source |
| Failed           | Red    | Encode failed                              |
| Cancelled        | Grey   | Manually cancelled                         |

---

## Encoding Settings

| Setting           | Value                                                       |
| ----------------- | ----------------------------------------------------------- |
| Video encoder     | Selectable — x264 or x265 (8-bit or 12-bit)                 |
| Quality mode      | Constant Quality (RF)                                       |
| Default RF        | 22 (Fast H.264) / 20 (H.265 presets)                        |
| Framerate         | Same as source; 50 fps → 25 fps                             |
| Resolution / crop | No change (pass-through)                                    |
| Audio             | Bitexact stream copy — codec, channels and layout preserved |
| Subtitles         | English only — Forced → Regular → SDH (never burned in)     |
| Container         | MKV                                                         |

---

## Post-encode Verification

After each file finishes, ffprobe checks that the output duration matches the source within a 2-second tolerance. The result is shown directly on the progress row:

- **✓ Safe to delete** — output verified, original can be removed
- **⚠ KEEP ORIGINAL** — duration mismatch detected, do not delete the source

The full detail (actual vs expected duration) is also written to the log.

---

## Audio Passthrough

Audio is copied bitexactly using ffmpeg's stream copy — no decoding or re-encoding takes place. This means:

- The original codec is preserved (AAC, AC3, EAC3, DTS, DTS-HD, TrueHD, FLAC, MP3, Opus…)
- Channel count and layout are preserved (stereo, 5.1, 7.1 etc.)
- Bitrate is preserved
- There is no quality loss

---

## Non-video Files

Files that aren't video (`.srt`, `.nfo`, artwork etc.) are copied to the mirrored output path the first time a video from that directory is encoded. Nothing is created upfront — if you stop halfway through, only the directories that were actually encoded will have their extras copied across.

---

## Why RF 20?

RF 20 gives excellent quality with meaningful compression over typical x264 source files. Nudge it up (e.g. 24–28) if you want smaller files at the cost of some quality.

---

## Supported Input Formats

`.mkv` `.mp4` `.avi` `.mov` `.ts` `.m2ts`

---

## License

MIT
