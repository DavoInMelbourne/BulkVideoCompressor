"""
HandBrake process detection, queue file injection, and launching.
"""
from __future__ import annotations
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import psutil

SYSTEM = platform.system()  # "Darwin", "Windows", "Linux"


# ---------------------------------------------------------------------------
# Orphan ffmpeg cleanup
# ---------------------------------------------------------------------------


def kill_orphan_ffmpeg(own_pid: int | None = None) -> int:
    """Kill leftover ffmpeg processes from previous runs that still hold
    VideoToolbox GPU encoder sessions.  Skips processes spawned by *this*
    Python process (``own_pid``, defaults to ``os.getpid()``).

    Returns the number of processes killed.
    """
    if own_pid is None:
        own_pid = os.getpid()

    killed = 0
    for proc in psutil.process_iter(["pid", "ppid", "name"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name not in ("ffmpeg", "ffprobe"):
                continue
            # Don't kill our own children — they'll be managed normally
            if proc.info["ppid"] == own_pid:
                continue
            # Graceful first, then hard
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


# ---------------------------------------------------------------------------
# Queue file location
# ---------------------------------------------------------------------------

def get_queue_file_path() -> Path:
    if SYSTEM == "Darwin":
        return Path.home() / "Library" / "Application Support" / "HandBrake" / "Queue.json"
    elif SYSTEM == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "HandBrake" / "Queue.json"
    else:  # Linux
        return Path.home() / ".config" / "ghb" / "queue.json"


# ---------------------------------------------------------------------------
# Locate HandBrake executables
# ---------------------------------------------------------------------------

_HANDBRAKE_GUI_NAMES = {
    "Darwin":  ["HandBrake"],
    "Windows": ["HandBrake.exe"],
    "Linux":   ["ghb", "HandBrake"],
}

_HANDBRAKE_CLI_NAMES = {
    "Darwin":  ["HandBrakeCLI"],
    "Windows": ["HandBrakeCLI.exe"],
    "Linux":   ["HandBrakeCLI"],
}

_HANDBRAKE_GUI_PATHS = {
    "Darwin":  ["/Applications/HandBrake.app/Contents/MacOS/HandBrake"],
    "Windows": [
        r"C:\Program Files\HandBrake\HandBrake.exe",
        r"C:\Program Files (x86)\HandBrake\HandBrake.exe",
    ],
    "Linux":   ["/usr/bin/ghb", "/usr/local/bin/ghb"],
}

_HANDBRAKE_CLI_PATHS = {
    "Darwin":  [
        "/Applications/HandBrakeCLI",
        "/usr/local/bin/HandBrakeCLI",
        "/opt/homebrew/bin/HandBrakeCLI",
        "/Applications/HandBrake.app/Contents/MacOS/HandBrakeCLI",
    ],
    "Windows": [
        r"C:\Program Files\HandBrake\HandBrakeCLI.exe",
        r"C:\Program Files (x86)\HandBrake\HandBrakeCLI.exe",
    ],
    "Linux":   ["/usr/bin/HandBrakeCLI", "/usr/local/bin/HandBrakeCLI"],
}


def _find_exe(paths: list[str], names: list[str]) -> Optional[Path]:
    # Check known paths
    for p in paths:
        if Path(p).exists():
            return Path(p)
    # Check PATH
    for name in names:
        try:
            result = subprocess.run(
                ["which" if SYSTEM != "Windows" else "where", name],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                found = result.stdout.strip().splitlines()[0]
                if found:
                    return Path(found)
        except Exception:
            pass
    return None


def find_handbrake_gui() -> Optional[Path]:
    return _find_exe(
        _HANDBRAKE_GUI_PATHS.get(SYSTEM, []),
        _HANDBRAKE_GUI_NAMES.get(SYSTEM, []),
    )


def find_handbrake_cli() -> Optional[Path]:
    return _find_exe(
        _HANDBRAKE_CLI_PATHS.get(SYSTEM, []),
        _HANDBRAKE_CLI_NAMES.get(SYSTEM, []),
    )


# ---------------------------------------------------------------------------
# Process detection
# ---------------------------------------------------------------------------

def _gui_process_names() -> list[str]:
    return {
        "Darwin":  ["HandBrake"],
        "Windows": ["HandBrake.exe"],
        "Linux":   ["ghb", "HandBrake"],
    }.get(SYSTEM, ["HandBrake"])


def _cli_process_names() -> list[str]:
    return {
        "Darwin":  ["HandBrakeCLI"],
        "Windows": ["HandBrakeCLI.exe"],
        "Linux":   ["HandBrakeCLI"],
    }.get(SYSTEM, ["HandBrakeCLI"])


def is_handbrake_running() -> bool:
    names = set(n.lower() for n in _gui_process_names() + _cli_process_names())
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in names:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


_IS_ENCODING_SCRIPT = """\
tell application "System Events"
    tell process "HandBrake"
        repeat with w in windows
            if title of w starts with "Encoding" then return "encoding"
            if title of w contains "Working" then return "encoding"
        end repeat
        -- Check dock tile / badge for encoding indicator
        return "idle"
    end tell
end tell
"""

_QUIT_SCRIPT = """\
tell application "HandBrake"
    quit saving no
end tell
"""


def is_handbrake_encoding() -> bool:
    """Best-effort check whether HandBrake is actively encoding (macOS only)."""
    if SYSTEM != "Darwin":
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e", _IS_ENCODING_SCRIPT],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() == "encoding"
    except Exception:
        return False


def quit_handbrake_gracefully() -> bool:
    """Ask HandBrake to quit (macOS: AppleScript quit; others: SIGTERM)."""
    if SYSTEM == "Darwin":
        try:
            subprocess.run(["osascript", "-e", _QUIT_SCRIPT], timeout=5)
        except Exception:
            pass
    else:
        names = set(n.lower() for n in _gui_process_names())
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() in names:
                    proc.terminate()
            except Exception:
                pass

    # Wait up to 15 s for HandBrake to exit
    for _ in range(30):
        time.sleep(0.5)
        if not is_handbrake_running():
            return True
    # Force kill as last resort
    names = set(n.lower() for n in _gui_process_names())
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in names:
                proc.kill()
        except Exception:
            pass
    time.sleep(1)
    return not is_handbrake_running()


# ---------------------------------------------------------------------------
# Queue injection
# ---------------------------------------------------------------------------

# HandBrake State values: 1=Waiting, 2=Working, 3=Completed, 4=Cancelled/Failed
_PENDING_STATES = {1, 2}


def read_existing_queue(queue_path: Path, pending_only: bool = True) -> list:
    if queue_path.exists():
        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                if pending_only:
                    return [j for j in data if j.get("State") in _PENDING_STATES]
                return data
        except Exception:
            pass
    return []


def write_queue(queue_path: Path, jobs: list) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)


def inject_queue(new_jobs: list[dict], queue_path: Optional[Path] = None,
                 replace: bool = False) -> Path:
    """Write new_jobs to the queue file. If replace=True, discard existing entries."""
    if queue_path is None:
        queue_path = get_queue_file_path()

    if replace:
        combined = new_jobs
    else:
        existing = read_existing_queue(queue_path)
        combined = existing + new_jobs
    write_queue(queue_path, combined)
    return queue_path


# ---------------------------------------------------------------------------
# macOS: trigger queue start in running HandBrake
# ---------------------------------------------------------------------------

_ACCESSIBILITY_SCRIPT = """\
tell application "System Events"
    tell process "HandBrake"
        set frontmost to true
        -- Show the queue window
        try
            perform action "AXRaise" of (first window whose title is "Queue")
        end try
        delay 0.3
        -- Click Start toolbar button (toggleStartCancel:)
        repeat with w in windows
            if title of w is "Queue" then
                repeat with tb in toolbars of w
                    repeat with btn in buttons of tb
                        if description of btn contains "Start" then
                            click btn
                            return "started"
                        end if
                    end repeat
                end repeat
                -- Fallback: try any button named Start in the window
                repeat with btn in buttons of w
                    if name of btn contains "Start" then
                        click btn
                        return "started"
                    end if
                end repeat
            end if
        end repeat
        return "no_start_button"
    end tell
end tell
"""

_ACCESSIBILITY_CHECK_SCRIPT = """\
tell application "System Events"
    return UI elements enabled
end tell
"""

_SHOW_QUEUE_AND_NOTIFY_SCRIPT = """\
tell application "HandBrake"
    activate
end tell
display notification "{msg}" with title "HandBrake Queue Manager" sound name "Glass"
"""

_OPEN_ACCESSIBILITY_PREFS = """\
tell application "System Preferences"
    activate
    set current pane to pane id "com.apple.preference.security"
end tell
"""


def check_accessibility() -> bool:
    """Return True if System Events UI scripting is permitted."""
    if SYSTEM != "Darwin":
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e", _ACCESSIBILITY_CHECK_SCRIPT],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip().lower() == "true"
    except Exception:
        return False


def trigger_queue_start_macos() -> str:
    """
    Attempt to bring HandBrake's Queue window to front and click Start.
    Returns one of: "started", "no_start_button", "no_accessibility", "error".
    """
    if SYSTEM != "Darwin":
        return "error"

    if not check_accessibility():
        # Activate HandBrake + fire a notification so user knows what to do
        try:
            subprocess.run(
                ["osascript", "-e",
                 _SHOW_QUEUE_AND_NOTIFY_SCRIPT.format(
                     msg="Jobs added — click Start in the Queue window"
                 )],
                timeout=5,
            )
        except Exception:
            pass
        return "no_accessibility"

    try:
        r = subprocess.run(
            ["osascript", "-e", _ACCESSIBILITY_SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        result = r.stdout.strip()
        return result if result else "error"
    except Exception as e:
        return "error"


def open_accessibility_preferences():
    """Open System Preferences → Security & Privacy → Accessibility."""
    if SYSTEM == "Darwin":
        try:
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                timeout=5,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Launch HandBrake GUI
# ---------------------------------------------------------------------------

def launch_handbrake(gui_path: Optional[Path] = None) -> bool:
    """Launch HandBrake GUI and wait until its process appears. Returns True on success."""
    if gui_path is None:
        gui_path = find_handbrake_gui()
    if gui_path is None:
        return False

    try:
        if SYSTEM == "Darwin":
            app_bundle = Path(str(gui_path))
            for parent in app_bundle.parents:
                if parent.suffix == ".app":
                    app_bundle = parent
                    break
            # -W would wait until app exits — don't use it; just launch
            result = subprocess.run(["open", str(app_bundle)], timeout=10)
            if result.returncode != 0:
                return False
        elif SYSTEM == "Windows":
            subprocess.Popen([str(gui_path)])
        else:
            subprocess.Popen([str(gui_path)])
    except Exception:
        return False

    # Wait up to 15 s for the HandBrake process to appear
    for _ in range(30):
        time.sleep(0.5)
        if is_handbrake_running():
            return True
    return False


# ---------------------------------------------------------------------------
# ffmpeg encoding
# ---------------------------------------------------------------------------

_FFMPEG_PATHS = {
    "Darwin":  ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"],
    "Windows": [r"C:\ffmpeg\bin\ffmpeg.exe"],
    "Linux":   ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"],
}

_ENCODER_MAP = {
    "x264":              "libx264",
    "x265":              "libx265",
    "x265_12bit":        "libx265",
    "av1":               "libsvtav1",
    "hevc_videotoolbox": "hevc_videotoolbox",
    "h264_videotoolbox": "h264_videotoolbox",
}


def find_ffmpeg() -> Optional[Path]:
    return _find_exe(_FFMPEG_PATHS.get(SYSTEM, []), ["ffmpeg"])


def find_ffprobe(ffmpeg_path: Optional[Path] = None) -> Optional[Path]:
    """Locate ffprobe — first checks alongside the known ffmpeg binary."""
    if ffmpeg_path is not None:
        name = "ffprobe.exe" if SYSTEM == "Windows" else "ffprobe"
        candidate = ffmpeg_path.parent / name
        if candidate.exists():
            return candidate
    # Fall back to searching standard paths / PATH
    probe_paths = {k: [p.replace("ffmpeg", "ffprobe") for p in v]
                   for k, v in _FFMPEG_PATHS.items()}
    return _find_exe(probe_paths.get(SYSTEM, []), ["ffprobe"])


def verify_output(ffprobe_path: Path, output: str,
                  expected_secs: float) -> tuple[bool, str]:
    """
    Two-stage verification:
      1. Duration check — output duration must match source within 2 seconds.
      2. Audio packet scan — reads every audio packet header looking for decode
         errors and timestamp discontinuities (the root cause of mid-file
         loud-bang / crash issues). Does not decode video frames so is fast.
    Returns (ok, message).
    """
    # ------------------------------------------------------------------
    # Stage 1: duration
    # ------------------------------------------------------------------
    try:
        r = subprocess.run(
            [
                str(ffprobe_path),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                output,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return False, "ffprobe could not read output file — keep original"
        actual = float(r.stdout.strip())
        if expected_secs > 0 and abs(actual - expected_secs) > 2.0:
            return False, (f"Duration mismatch: source {expected_secs:.1f}s, "
                           f"output {actual:.1f}s — keep original")
    except Exception as e:
        return False, f"Duration check error: {e}"

    # ------------------------------------------------------------------
    # Stage 2: audio packet scan
    # Reads packet timestamps for the first audio stream without decoding.
    # Checks for:
    #   - Any stderr output from ffprobe (indicates read/container errors)
    #   - Timestamp gaps > 1 second (missing audio — causes loud bang)
    #   - Non-monotonic timestamps (causes desync / bang)
    # ------------------------------------------------------------------
    proc = None
    try:
        proc = subprocess.Popen(
            [
                str(ffprobe_path),
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "packet=pts_time,size",
                "-of", "csv=p=0",
                output,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        prev = None
        deadline = time.monotonic() + 180  # 3-minute timeout
        for raw_line in proc.stdout:
            if time.monotonic() > deadline:
                proc.kill()
                proc.wait(timeout=5)
                return False, "Audio scan timed out — keep original"
            line = raw_line.decode("utf-8", errors="replace").strip()
            parts = line.split(",")
            if not parts or parts[0] in ("", "N/A"):
                continue
            try:
                t = float(parts[0])
            except ValueError:
                continue
            if prev is not None:
                gap = t - prev
                if gap > 1.0:
                    return False, (f"Audio gap of {gap:.1f}s at {prev:.1f}s "
                                   f"— keep original")
                if gap < -0.1:
                    return False, (f"Audio timestamp jump at {prev:.1f}s "
                                   f"— keep original")
            prev = t

        proc.wait(timeout=10)
        stderr_out = proc.stderr.read().decode("utf-8", errors="replace").strip()
        if stderr_out:
            return False, f"Audio stream errors detected — keep original"

    except Exception as e:
        return False, f"Audio scan error: {e}"
    finally:
        if proc:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
            for pipe in (proc.stdout, proc.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass

    return True, f"verified {actual:.1f}s — safe to delete"


def run_cli_job(
    cli_path: Path,
    source: str,
    output: str,
    rf: float,
    fps: float,
    audio_index: int,
    subtitle_indices: list[int],
    subtitle_forced_index: Optional[int],
    encoder: str = "x265",
    encoder_preset: str = "medium",
    progress_file: Optional[str] = None,
) -> subprocess.Popen:
    """Encode a single file with ffmpeg. Audio is copied bitexactly.

    If *progress_file* is given, ffmpeg writes structured progress to that
    file and stdout/stderr are silenced.  The caller polls the file instead
    of reading a pipe — this eliminates any pipe backpressure that could
    stall the encoder.
    """
    ffmpeg_encoder = _ENCODER_MAP.get(encoder, "libx265")

    args = [str(cli_path)]

    # Use hardware decoding when paired with a hardware encoder — offloads
    # decode to Apple's dedicated media engine, keeping CPU cool and
    # preventing thermal throttling during long encodes.
    if encoder in ("hevc_videotoolbox", "h264_videotoolbox"):
        args += ["-hwaccel", "videotoolbox"]

    # Increase probe limits so ffmpeg can read codec parameters for all
    # streams in large REMUX files (e.g. PGS subtitles, TrueHD/DTS-HD MA).
    args += ["-probesize", "100M", "-analyzeduration", "100M"]

    args += [
        "-i", source,
        # Select streams
        "-map", "0:v:0",
        "-map", f"0:a:{audio_index - 1}",   # 0-based audio stream index
    ]

    for si in subtitle_indices:
        args += ["-map", f"0:s:{si - 1}"]   # 0-based subtitle stream index

    args += ["-c:v", ffmpeg_encoder]
    if encoder in ("hevc_videotoolbox", "h264_videotoolbox"):
        # VideoToolbox uses -q:v (0–100, higher = better quality) instead of CRF/preset
        args += ["-q:v", str(int(rf)), "-allow_sw", "1"]
        # hvc1 tag ensures broad compatibility with Apple devices and smart TVs
        if encoder == "hevc_videotoolbox":
            args += ["-tag:v", "hvc1"]
    else:
        args += ["-crf", str(rf)]
        if encoder_preset:
            args += ["-preset", encoder_preset]

    # 50 fps → 25 fps
    if abs(fps - 50.0) < 1.0:
        args += ["-r", "25"]

    args += [
        # Audio: bitexact stream copy — preserves codec, channels, and layout
        "-c:a", "copy",
        # Subtitles: stream copy
        "-c:s", "copy",
        # Allow a larger muxer queue so DTS-HD MA / TrueHD audio packets can
        # be buffered without blocking video encoding (fixes time=N/A in
        # progress output for REMUX files with lossless audio tracks).
        "-max_muxing_queue_size", "9999",
    ]

    # Mark the first subtitle stream as default+forced if it is a forced track
    if subtitle_forced_index is not None:
        args += ["-disposition:s:0", "default+forced"]

    # Overwrite output without prompting
    args += ["-y", output]

    if progress_file:
        # Write structured progress to a file; silence all console output
        # so ffmpeg never blocks on a pipe write.
        args += ["-progress", progress_file]
        return subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Legacy: pipe-based progress (used by tests / non-VideoToolbox)
    return subprocess.Popen(
        args,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    )
