# Bulk Video Compressor

A lightweight macOS desktop app that batch-compresses video files using ffmpeg. Scan a folder, review the detected settings, and let it encode — all with a clean progress UI.

Built for people who want to compress a library of movies or TV shows quickly without manually adding files to an encoder one by one. Point it at a folder and walk away.

![Python](https://img.shields.io/badge/python-3.11+-blue) ![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-green) ![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)

---

## Author

Made with 💛 by **[Paul Davies](https://github.com/DavoInMelbourne)**

**Like this project?** Help keep the lights on at [weluvbeer.com](https://www.weluvbeer.com) by buying me a Ko-fi!

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/weluvbeer)

---

## Features

- Recursively scans a source folder for video files across any number of subdirectories
- Handles files with or without a dedicated container folder
- Auto-detects resolution, FPS, codec, file size, audio tracks and subtitles per file
- Review all files before encoding — see exactly what will be processed and which will be remuxed or skipped
- **Encoding presets** — separate presets for 1080p and 4K content:
  - **Fast H.264 (Hardware)** — VideoToolbox h264, quality 50
  - **Fast H.265 (Hardware)** — VideoToolbox HEVC, quality 50 (default for 4K)
  - **Fast H.264** — x264, fast preset, RF 22
  - **Balanced H.265** — x265, medium preset, RF 20
  - **Quality H.265 12-bit** — x265 12-bit, medium preset, RF 20 (default for 1080p)
  - **Quality AV1** — SVT-AV1, preset 4, RF 30
- **HDR passthrough** — when encoding 4K HDR content with VideoToolbox, explicit BT.2020 / SMPTE ST 2084 colour flags are applied to ensure HDR metadata is preserved
- **Smart Skip** — automatically identifies hevc/av1 files that are already efficiently compressed and routes them through the appropriate path without re-encoding:
  - Configurable size thresholds — separate limits for 4K (default: 20 GB) and 1080p & below (default: 4 GB)
  - **Remux** — if the file has multiple audio tracks or more subtitle tracks than will be kept, the video is copied bitexactly and the unwanted tracks are dropped. Produces a smaller file with no quality loss. Output written to the output directory
  - **True skip** — if the file is already clean (single audio track, no subtitle tracks to drop), the file is copied as-is to the output directory. No ffmpeg processing needed
- Audio **bitexact stream copy** — the original audio is copied byte-for-byte, preserving codec, channels, channel layout and bitrate
- **Smart audio track selection** — configurable language preference with automatic fallback; prefers DTS/TrueHD within the chosen language, then falls back to the fallback language, then the first available track
- **Commentary track filtering** — audio tracks whose title contains "commentary", "director", "interview", "description" or "narration" are automatically excluded from selection
- **Language Preferences** — independent dropdowns for audio track language, subtitle language, and a fallback language used when the preferred language is not found:
  - **Original Language** (default) — uses the language of the first audio track in each file, so a mixed batch of English, Korean, French films each picks its own native language automatically
  - **Non-English** — always picks the first non-English track, regardless of language; useful for batches of foreign-language content
  - **Specific language** — force a particular language (English, Korean, Japanese, Thai, Vietnamese, French, German, Italian, Spanish, Dutch, Portuguese, Chinese, Polish, Danish, Swedish, Finnish, Norwegian) for the whole batch
- **Prioritise DTS** — when checked, DTS and TrueHD tracks are preferred within the selected language
- **Subtitle language** — independently selectable; always defaults to English; falls back to the fallback language, then English if the chosen language is not present
- Subtitles passed through at most 1 Forced + 1 Regular + 1 SDH per file, never burned in
- Mirrors source folder structure in the output directory
- Copies non-video files (subtitles, artwork, NFO etc.) per-directory as each directory is encoded
- **Post-encode verification** — two-stage check using ffprobe:
  1. Duration check — output must match source within 2 seconds
  2. Audio packet scan — streams every audio packet timestamp looking for gaps (>1s) and backwards jumps that cause loud-bang / desync issues
- **Reverse compression detection** — if the output is larger than the source, the original is copied to the output path instead
- **Post-processing** — automatically rename and clean up after encoding:
  - Successful encode: output folder (or file) renamed with a custom suffix, e.g. `Movie.Done`
  - Remux: output folder (or file) renamed with a separate remux suffix, e.g. `Movie.Remux`
  - True skip: file copied to output directory and renamed with the skip suffix, e.g. `Movie.Skip`
  - Failed encode or zero compression (output no smaller than source): source folder renamed with the problem suffix, e.g. `Movie.Check`; source file is copied to the output so nothing is lost
  - Orphaned extras (subtitles, artwork etc.) are cleaned up if an encode fails partway through
  - Optionally delete the source file/folder after a verified successful encode — applies to remux and true skip paths too
- Scrollable per-file progress panel with FPS and ETA
- Cancel individual files or stop everything immediately
- Dismiss completed rows individually or clear all finished files
- Add more files to the queue while encoding is already running
- **Thermal throttle safeguards** — monitors encoding FPS and automatically pauses to let the machine cool down when performance degrades, plus proactive scheduled cooldowns to prevent overheating during long batches
- **Process safety** — graceful SIGTERM shutdown for ffmpeg (preserves VideoToolbox GPU encoder sessions), orphan process cleanup on startup, bounded memory buffers, explicit pipe closure

---

## Download

**Don't want to use the terminal?** Grab the latest built app from the [Releases page](https://github.com/DavoInMelbourne/BulkVideoCompressor/releases).

1. Download `BulkVideoCompressor.app.zip`
2. Unzip and drag to your Applications folder
3. Right-click → **Open** the first time to get past macOS Gatekeeper
4. Grant **Full Disk Access** in System Settings → Privacy & Security → Full Disk Access

> ffmpeg is still required: `brew install ffmpeg`

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
5. **Audio Language** — preferred audio track language for the batch (see Language Preferences above)
6. **Subtitles** — preferred subtitle language (default: English)
7. **Fallback** — language used for both audio and subtitles if the preferred language is not found in a file
8. **Prioritise DTS** — when checked, DTS and TrueHD tracks are preferred within the selected language
9. **RF Quality** — Constant Quality value (set automatically by preset; lower = better quality / larger file for software encoders; higher = better quality for VideoToolbox)
10. **Skip 4K if under** — hevc/av1 files at 4K below this size are remuxed or skipped rather than re-encoded (default: 20 GB)
11. **Skip 1080p & below if under** — hevc/av1 files at 1080p and below below this size are remuxed or skipped (default: 4 GB)
12. **Success suffix** — text appended to the output folder/file on a successful encode (e.g. `Done` → `Movie.Done`)
13. **Problem suffix** — text appended to the source folder/file on failure (e.g. `Check` → `Movie.Check`)
14. **Skip suffix** — text appended to the output folder/file for true skips (e.g. `Skip` → `Movie.Skip`)
15. **Remux suffix** — text appended to the output folder/file after a remux (e.g. `Remux` → `Movie.Remux`)
16. **After success** — what to do with the source file/folder after a verified successful result (Keep / Move to Bin / Delete Permanently); applies to encode, remux and true skip paths
17. **Min FPS** — minimum expected encoding FPS at 10% progress (see Thermal Safeguards below)
18. **Cool every / for** — proactive cooldown interval (see Thermal Safeguards below)
19. **ffmpeg Path** — auto-detected; override if needed
20. Click **Scan & Review** to inspect detected settings
21. Click **Add to Queue** to start encoding

### Smart Skip decision logic

When a file is probed as hevc or av1 and falls below the configured size threshold, it is routed automatically:

| Condition | Action |
|---|---|
| Multiple audio tracks **or** subtitle tracks would be dropped | **Remux** — video copied bitexactly, selected audio + subtitles kept, rest dropped |
| Single audio track **and** all subtitle tracks would be kept | **True skip** — copied as-is to output directory, no ffmpeg processing |

In all cases the output ends up in the output directory and the configured suffix is applied.

### Post-processing behaviour

| Scenario | Has container folder | Result |
|---|---|---|
| Encode success | Yes | Output folder renamed, e.g. `Movie` → `Movie.Done` |
| Encode success | No (file in root) | Output file renamed, e.g. `Movie.mkv` → `Movie.Done.mkv` |
| Remux success | Yes | Output folder renamed with remux suffix, e.g. `Movie` → `Movie.Remux` |
| Remux success | No (file in root) | Output file renamed, e.g. `Movie.mkv` → `Movie.Remux.mkv` |
| True skip | Yes | File copied to output folder, folder renamed with skip suffix, e.g. `Movie` → `Movie.Skip` |
| True skip | No (file in root) | File copied to output, renamed e.g. `Movie.mkv` → `Movie.Skip.mkv` |
| Failed/error | Yes | Source folder renamed, e.g. `Movie` → `Movie.Check` |
| Failed/error | No (file in root) | Source file renamed, e.g. `Movie.mkv` → `Movie.Check.mkv` |
| Delete source | Yes | Source file deleted, then source folder deleted |
| Delete source | No (file in root) | Source file deleted only (root folder is never deleted) |

### Status badges

| Badge                | Colour | Meaning                                        |
| -------------------- | ------ | ---------------------------------------------- |
| Waiting              | Grey   | Queued, not yet started                        |
| Encoding             | Blue   | Currently being encoded                        |
| Remuxing             | Blue   | Stream copy in progress (no re-encode)         |
| Running large        | Orange | Output is tracking larger than source at 25%   |
| Scanning...          | Orange | Post-encode audio packet scan in progress      |
| Safe to delete       | Green  | Verified — original can be removed (shows final FPS) |
| Keep original        | Red    | Verification failed — do not delete source     |
| Reverse compression  | Purple | Output was larger — original copied to output  |
| Problem file         | Orange | File cannot reach minimum FPS threshold        |
| Skipped              | Grey   | True skip — already clean, copied to output    |
| Failed               | Red    | Encode failed                                  |
| ERROR                | Red    | Unexpected crash (caught and logged)           |
| Cancelled            | Grey   | Manually cancelled                             |

---

## Encoding Settings

| Setting           | Value                                                        |
| ----------------- | ------------------------------------------------------------ |
| Video encoder     | Selectable per resolution — x264, x265, AV1, or VideoToolbox |
| Quality mode      | Constant Quality (RF) or VideoToolbox quality level           |
| Framerate         | Same as source; 50 fps is halved to 25 fps (encode only)     |
| Resolution / crop | No change (pass-through)                                     |
| Audio             | Bitexact stream copy — codec, channels and layout preserved  |
| Subtitles         | Forced, Regular, SDH — stream copy, never burned in          |
| HDR               | BT.2020 / PQ colour flags preserved on 4K HDR VideoToolbox encodes |
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
- **Stall detection** — if ffmpeg produces no measurable encoding progress for 10 minutes, the process is terminated. Files with lossless audio (DTS-HD MA, TrueHD) that report `time=N/A` are handled correctly — activity is detected via FPS output so they are never incorrectly killed.
- **Bounded buffers** — the progress-reading buffer is capped at 8KB to prevent unbounded memory growth.
- **Pipe cleanup** — stdout pipes are explicitly closed after every encode to prevent file descriptor leaks.
- **Streaming verification** — audio packet scanning streams ffprobe output line-by-line instead of loading it all into memory.
- **Memory monitoring** — each ffmpeg process is watched via psutil; if RSS exceeds 12GB the encode is killed with a clear error.
- **App Nap prevention** — `caffeinate -dims` runs during encoding to prevent macOS from throttling ffmpeg when the screen is locked or idle.
- **Large file support** — the encode queue correctly handles files of any size; post-processing runs asynchronously so a slow verification scan on a large output file does not stall the queue.

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
    languages.py           # Language enum (audio/subtitle language preferences)
    mediainfo.py           # Video file probing (metadata extraction)
    queue_builder.py       # Audio/subtitle track selection logic
    scanner.py             # Directory scanning and output path mapping
  ui/
    main_window.py         # Main UI, queue management, state machine
    workers.py             # Background threads (ProbeWorker, EncodeWorker)
    review_dialog.py       # Pre-encoding review modal
  tests/
    test_process_cleanup.py  # 33 tests covering process safety and thermal safeguards
```

---

## Cutting a Release

When you're ready to publish a new version:

```bash
# 1. Build the app
pip install pyinstaller
pyinstaller --onefile --windowed --name "BulkVideoCompressor" main.py

# 2. Zip it (GitHub needs a zip — .app files are actually folders)
cd dist && zip -r BulkVideoCompressor.app.zip BulkVideoCompressor.app && cd ..

# 3. Tag the release in git
git tag v1.0.0
git push origin v1.0.0
```

Then on GitHub:
- Go to **Releases** → **Draft a new release**
- Pick the tag you just pushed
- Attach `dist/BulkVideoCompressor.app.zip`
- Publish

> **Local use:** drag `dist/BulkVideoCompressor.app` straight to your Applications folder — no need to zip.
>
> **GitHub Release:** attach the `.zip` — when users download and unzip it they get the `.app`.

The download link in this README will point users straight to the Releases page.

---

## License

MIT
