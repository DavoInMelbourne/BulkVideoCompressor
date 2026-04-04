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

- Recursively scans a source folder for video files across any number of subdirectories
- Auto-detects resolution, FPS, audio tracks and subtitles per file
- Review all files before encoding — see exactly what will be processed
- **Encoding presets** — separate presets for 1080p and 4K content:
  - **Fast H.264 (Hardware)** — VideoToolbox h264, quality 50
  - **Fast H.265 (Hardware)** — VideoToolbox HEVC, quality 50 (default)
  - **Fast H.264** — x264, fast preset, RF 22
  - **Balanced H.265** — x265, medium preset, RF 20
  - **Quality H.265 12-bit** — x265 12-bit, medium preset, RF 20
  - **Quality AV1** — SVT-AV1, preset 4, RF 30
- Audio **bitexact stream copy** — the original audio is copied byte-for-byte, preserving codec, channels, channel layout and bitrate
- English or Foreign audio track preference
- Subtitles passed through (Forced, Regular, SDH), never burned in
- Mirrors source folder structure in the output directory
- Copies non-video files (subtitles, artwork, NFO etc.) per-directory as each directory is encoded
- **Post-encode verification** — two-stage check using ffprobe:
  1. Duration check — output must match source within 2 seconds
  2. Audio packet scan — streams every audio packet timestamp looking for gaps (>1s) and backwards jumps that cause loud-bang / desync issues
- **Reverse compression detection** — if the output is larger than the source, the original is copied to the output path instead
- Scrollable per-file progress panel with FPS and ETA
- Cancel individual files or stop everything immediately
- Dismiss completed rows individually or clear all finished files
- Add more files to the queue while encoding is already running
- **Thermal throttle safeguards** — monitors encoding FPS and automatically pauses to let the machine cool down when performance degrades, plus proactive scheduled cooldowns to prevent overheating during long batches
- **Process safety** — graceful SIGTERM shutdown for ffmpeg (preserves VideoToolbox GPU encoder sessions), orphan process cleanup on startup, bounded memory buffers, explicit pipe closure

---

## Prerequisites

- **Python 3.9+**
- **ffmpeg** and **ffprobe** — install via Homebrew: `brew install ffmpeg`
- **MediaInfo** (optional, falls back to ffprobe) — `brew install mediainfo`

---

## Quick Start

```bash
git clone https://github.com/DavoInMelbourne/BulkVideoCompressor.git
cd BulkVideoCompressor

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python3 main.py
```

---

## Commands

### Run the app

```bash
python3 main.py
```

### Run the tests

```bash
pip install pytest
python3 -m pytest tests/ -v
```

### Build a standalone macOS app (optional)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "BulkVideoCompressor" main.py
```

The app will be in `dist/`.

---

## Usage

1. **Source Directory** — folder to scan (recursive)
2. **Output Directory** — where encoded files are written, mirroring the source structure
3. **1080p Preset** — encoding preset for content below 4K
4. **4K Preset** — encoding preset for 2160p/3840p+ content
5. **Audio Language** — prefer English or Foreign track
6. **RF Quality** — Constant Quality value (set automatically by preset; lower = better quality / larger file)
7. **Min FPS** — minimum expected encoding FPS at 10% progress (see Thermal Safeguards below)
8. **Cool every / for** — proactive cooldown interval (see Thermal Safeguards below)
9. **ffmpeg Path** — auto-detected; override if needed
10. Click **Scan & Review** to inspect detected settings
11. Click **Add to Queue** to start encoding

### Status badges

| Badge                | Colour | Meaning                                        |
| -------------------- | ------ | ---------------------------------------------- |
| Waiting              | Grey   | Queued, not yet started                        |
| Encoding             | Blue   | Currently being encoded                        |
| Running large        | Orange | Output is tracking larger than source at 25%   |
| Scanning...          | Orange | Post-encode audio packet scan in progress      |
| Safe to delete       | Green  | Verified — original can be removed (shows final FPS) |
| Keep original        | Red    | Verification failed — do not delete source     |
| Reverse compression  | Purple | Output was larger — original copied to output  |
| Problem file         | Orange | File cannot reach minimum FPS threshold        |
| Failed               | Red    | Encode failed                                  |
| ERROR                | Red    | Unexpected crash (caught and logged)           |
| Cancelled            | Grey   | Manually cancelled                             |

---

## Encoding Settings

| Setting           | Value                                                        |
| ----------------- | ------------------------------------------------------------ |
| Video encoder     | Selectable per resolution — x264, x265, AV1, or VideoToolbox |
| Quality mode      | Constant Quality (RF) or VideoToolbox quality level           |
| Framerate         | Same as source; 50 fps is halved to 25 fps                   |
| Resolution / crop | No change (pass-through)                                     |
| Audio             | Bitexact stream copy — codec, channels and layout preserved  |
| Subtitles         | Forced, Regular, SDH — stream copy, never burned in          |
| Container         | MKV                                                          |

---

## Thermal Safeguards

Long batch encodes are vulnerable to two things that silently kill FPS: thermal throttling and macOS power management. The app handles both automatically.

### App Nap prevention (`caffeinate`)

When you lock your screen or leave your Mac idle, macOS aggressively throttles background processes via App Nap — FPS can drop from 250 to single digits even though the machine is cold. The app automatically runs `caffeinate -dims` while encoding is active, which prevents display sleep, idle sleep, disk sleep, and system sleep. This keeps ffmpeg running at full speed even when you walk away. `caffeinate` is stopped automatically when encoding finishes or the app is closed.

### How it works

1. **Baseline capture** — on the first file, at 10% progress, the app records the current FPS as the baseline and displays it on the form (e.g. `250 Base FPS`). If the baseline is below your **Min FPS** setting, encoding stops with a prompt to lower the value.

2. **Problem file detection** — if a file can't reach the Min FPS threshold at 10% progress, it's retried after a 10-second pause. If it still can't hit the threshold, it's marked as a problem file (orange) and skipped.

3. **Proactive cooldown** — a scheduled pause is inserted every N files (default: 10) for a configurable duration (default: 2 minutes). This prevents thermal buildup before it starts affecting FPS.

4. **Batch summary** — at the end of a run, a summary shows total files processed, problem files, and total cooldown time.

### Recommended settings

| Setting    | Default | Notes |
| ---------- | ------- | ----- |
| Min FPS    | 200     | Suitable for most modern machines (less than ~2 years old). Lower this if your machine consistently runs below 200 FPS — the baseline will tell you where your machine sits. |
| Cool every | 10 files | How often to insert a proactive cooldown. Increase if your machine stays cool, reduce if it runs hot. |
| Cool for   | 2.0 min  | Duration of each proactive cooldown. The defaults are intentionally proactive to keep throughput high, but can be tailored per machine. |

---

## Process Safety

The app is designed for unattended overnight batch encoding. Key safeguards:

- **Graceful process shutdown** — ffmpeg is sent SIGTERM first, with a 5-second window to release VideoToolbox hardware encoder sessions. SIGKILL is only used as a fallback. This prevents GPU encoder slot exhaustion that causes progressive FPS degradation.
- **Orphan cleanup** — on startup, any leftover ffmpeg/ffprobe processes from a previous crash are detected and killed.
- **Stall detection** — if ffmpeg produces no progress output for 10 minutes, the process is terminated.
- **Bounded buffers** — the progress-reading buffer is capped at 8KB to prevent unbounded memory growth.
- **Pipe cleanup** — stdout pipes are explicitly closed after every encode to prevent file descriptor leaks.
- **Streaming verification** — audio packet scanning streams ffprobe output line-by-line instead of loading it all into memory.
- **8GB memory limit** — each ffmpeg process is capped via `RLIMIT_AS` (macOS/Linux).
- **App Nap prevention** — `caffeinate -dims` runs during encoding to prevent macOS from throttling ffmpeg when the screen is locked or idle.

---

## Supported Input Formats

`.mkv` `.mp4` `.avi` `.mov` `.ts` `.m2ts`

---

## Project Structure

```
BulkVideoCompressor/
  main.py                  # App entry point
  requirements.txt         # Python dependencies
  core/
    handbrake.py           # ffmpeg process management, verification, orphan cleanup
    mediainfo.py           # Video file probing (metadata extraction)
    queue_builder.py       # Audio/subtitle track selection
    scanner.py             # Directory scanning and output path mapping
  ui/
    main_window.py         # Main UI, queue management, state machine
    workers.py             # Background threads (ProbeWorker, EncodeWorker)
    review_dialog.py       # Pre-encoding review modal
  tests/
    test_process_cleanup.py  # 33 tests covering process safety and thermal safeguards
```

---

## License

MIT
