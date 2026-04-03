"""
Background workers for probing and encoding video files.
"""
from __future__ import annotations

import itertools
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.handbrake import run_cli_job, verify_output
from core.mediainfo import probe_file
from core.queue_builder import select_audio_track, select_subtitle_tracks
from core.scanner import get_output_path, scan_directory


def _parse_time(t: str) -> float:
    """Parse ffmpeg time string HH:MM:SS.xx to seconds."""
    try:
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(parts[-1])
    except (ValueError, IndexError):
        return 0.0


def _fmt_eta(secs: float) -> str:
    secs = int(max(0, secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


_id_gen = itertools.count()  # unique task IDs


# ---------------------------------------------------------------------------
# Probe worker
# ---------------------------------------------------------------------------


class ProbeWorker(QThread):
    log = pyqtSignal(str)
    probed = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, source_dir, output_dir, prefer_english):
        super().__init__()
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.prefer_english = prefer_english

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.failed.emit(str(e))

    def _run(self):
        source_root = Path(self.source_dir)
        output_root = Path(self.output_dir)

        self.log.emit(f"Scanning: {source_root}")
        files = scan_directory(self.source_dir)
        if not files:
            self.failed.emit("No video files found in source directory.")
            return

        self.log.emit(f"Found {len(files)} file(s) — probing…\n")
        tasks = []
        for f in files:
            out = get_output_path(f, source_root, output_root)
            self.log.emit(f"  {f.name}")
            try:
                info = probe_file(f)
            except Exception as e:
                self.log.emit(f"    ⚠ Probe failed: {e}")
                continue
            tasks.append(
                {
                    "id": next(_id_gen),
                    "source": f,
                    "output": out,
                    "info": info,
                    "audio": select_audio_track(info.audio_tracks, self.prefer_english),
                    "subs": select_subtitle_tracks(info.subtitle_tracks),
                }
            )
        self.probed.emit(tasks)


# ---------------------------------------------------------------------------
# Encode worker — processes a SINGLE task then exits (new thread per file)
# ---------------------------------------------------------------------------

# Stall timeout: if ffmpeg produces no progress output for this many seconds,
# the process is killed.  Prevents hung encodes from blocking the queue and
# leaking GPU encoder sessions.
_STALL_TIMEOUT = 600  # 10 minutes


class EncodeWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int, float, str)  # row_index, pct, fps, eta
    task_done = pyqtSignal(int, bool)  # row_index, success
    verified = pyqtSignal(int, bool, str)  # row_index, ok, message
    reverse_compression = pyqtSignal(int, str)  # row_index, message
    skipped = pyqtSignal(int)  # row_index
    size_warning = pyqtSignal(int)  # row_index — output already larger than source at 25%
    crashed = pyqtSignal(int, str)  # row_index, error message
    # QThread.finished is used directly — defining it here causes a double-fire

    # ffmpeg progress line: "frame= 123 fps= 45.2 ... time=00:00:05.12 ... speed=1.82x"
    _PCT_RE = re.compile(
        r"fps=\s*([\d.]+).*?time=([\d:]+\.[\d]*).*?speed=\s*([\d.]+)x",
        re.IGNORECASE,
    )

    def __init__(
        self,
        task: dict,
        row: int,
        cancelled: set,
        copied_dirs: set,
        cli_path: Path,
        ffprobe_path,
        rf: float,
        encoder: str = "x265",
        encoder_preset: str = "medium",
    ):
        super().__init__()
        self.task = task
        self.row = row
        self.cancelled = cancelled
        self.copied_dirs = copied_dirs  # shared reference from MainWindow
        self.cli_path = cli_path
        self.ffprobe_path = ffprobe_path
        self.rf = rf
        self.encoder = encoder
        self.encoder_preset = encoder_preset
        self._current_proc = None
        self._current_id = None

    def run(self):
        t = self.task
        if t["id"] in self.cancelled:
            self.skipped.emit(self.row)
            return
        self._current_id = t["id"]
        try:
            self._encode(t, self.row)
        except Exception as e:
            # Top-level safety net: catch ANY unhandled exception so the
            # queue keeps moving and ffmpeg never leaks a GPU session.
            self.log.emit(f"  ✗ CRASH caught: {e}\n")
            self._kill_proc_hard()
            self._cleanup_partial(t["output"])
            self.crashed.emit(self.row, str(e))
        finally:
            self._current_id = None
            self._kill_proc_hard()
        # QThread.finished fires automatically when run() returns

    def _kill_proc_hard(self):
        """Ensure the ffmpeg subprocess is dead — prevents leaked GPU sessions."""
        proc = self._current_proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        except Exception:
            pass
        self._current_proc = None

    def cancel_current(self):
        """Kill the currently-running encode process."""
        if self._current_proc and self._current_proc.poll() is None:
            self._current_proc.kill()

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------

    def _encode(self, t: dict, row: int):
        f, out = t["source"], t["output"]
        info = t["info"]
        audio = t["audio"]
        subs = t["subs"]

        out.parent.mkdir(parents=True, exist_ok=True)
        self._copy_extras(f, out)

        audio_index = audio.index if audio else 1
        sub_indices = [s.index for s in subs]
        forced_idx = next((s.index for s in subs if s.forced), None)

        encoder = t.get("encoder", self.encoder)
        encoder_preset = t.get("encoder_preset", self.encoder_preset)
        rf = t.get("rf", self.rf)

        self.log.emit(f"[{row + 1}] Encoding: {f.name}")
        self.progress.emit(row, 0, 0.0, "Starting…")
        proc = None
        try:
            proc = run_cli_job(
                cli_path=self.cli_path,
                source=str(f),
                output=str(out),
                rf=rf,
                fps=info.fps,
                audio_index=audio_index,
                subtitle_indices=sub_indices,
                subtitle_forced_index=forced_idx,
                encoder=encoder,
                encoder_preset=encoder_preset,
            )
            self._current_proc = proc
            self._read_progress(proc, t, row)
        except Exception as e:
            self.log.emit(f"  ✗ Encoding error: {e}\n")
            self.task_done.emit(row, False)
            self._cleanup_partial(out)
            return
        finally:
            # Always ensure ffmpeg is dead — leaked VideoToolbox sessions
            # exhaust GPU encoder slots and can crash the system.
            if proc and proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass

        self._handle_result(proc, t, row)

    def _read_progress(self, proc, t: dict, row: int):
        """Read ffmpeg stdout, emit progress signals, kill stalled encodes."""
        duration = t["info"].duration_secs
        src_size = t["source"].stat().st_size
        out = t["output"]
        buf = ""
        _size_checked = False
        _last_progress = time.monotonic()

        for chunk in iter(lambda: proc.stdout.read(256), b""):
            buf += chunk.decode("utf-8", errors="replace")
            while "\r" in buf:
                line, buf = buf.split("\r", 1)
                m = self._PCT_RE.search(line)
                if m:
                    _last_progress = time.monotonic()
                    fps = float(m.group(1))
                    cur = _parse_time(m.group(2))
                    speed = float(m.group(3)) or 0.001
                    pct = int(min(99, cur / duration * 100)) if duration > 0 else 0
                    eta = _fmt_eta((duration - cur) / speed) if duration > 0 else ""
                    self.progress.emit(row, pct, fps, eta)
                    if not _size_checked and pct >= 25:
                        _size_checked = True
                        try:
                            if out.exists() and out.stat().st_size > src_size * 0.25:
                                self.size_warning.emit(row)
                        except Exception:
                            pass
            # Kill stalled encodes that stop producing output
            if time.monotonic() - _last_progress > _STALL_TIMEOUT:
                self.log.emit(f"  ✗ Encode stalled for {_STALL_TIMEOUT}s — killing\n")
                proc.kill()
                break

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    def _handle_result(self, proc, t: dict, row: int):
        """Process the encode result: verify output, check reverse compression."""
        f, out = t["source"], t["output"]
        cancelled = t["id"] in self.cancelled
        ok = proc.returncode == 0 and not cancelled

        if cancelled:
            self.skipped.emit(row)
            self.log.emit("  ✗ Cancelled\n")
            self._cleanup_partial(out)
            return

        self.progress.emit(row, 100 if ok else 0, 0, "")
        self.task_done.emit(row, ok)
        self.log.emit(
            f"  {'✓ Done' if ok else f'✗ Failed (exit {proc.returncode})'}\n"
        )
        if not ok:
            self._cleanup_partial(out)
            return

        if not self.ffprobe_path:
            return

        self.log.emit("  Scanning output for errors…")
        v_ok, v_msg = verify_output(
            self.ffprobe_path, str(out), t["info"].duration_secs
        )
        self.verified.emit(row, v_ok, v_msg)
        self.log.emit(f"  {'✓' if v_ok else '⚠'} {v_msg}\n")

        # Check for reverse compression (output larger than source)
        if v_ok:
            self._check_reverse_compression(f, out, row)

    def _check_reverse_compression(self, f: Path, out: Path, row: int):
        try:
            src_size = f.stat().st_size
            out_size = out.stat().st_size
            if out_size >= src_size:
                pct = ((out_size / src_size) - 1) * 100
                msg = (f"Output is {pct:.0f}% larger than source "
                       f"({out_size // (1024*1024)}MB vs "
                       f"{src_size // (1024*1024)}MB)")
                self.log.emit(f"  ⚠ Reverse compression: {msg}")
                self._trash_file(out)
                try:
                    shutil.copy2(str(f), str(out))
                    self.log.emit(f"  Copied original to output: {out.name}")
                except OSError as e:
                    self.log.emit(f"  ⚠ Could not copy original: {e}")
                self.reverse_compression.emit(row, msg)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _copy_extras(self, f: Path, out: Path):
        """Copy non-video files from the source directory (first time only)."""
        if f.parent in self.copied_dirs:
            return
        self.copied_dirs.add(f.parent)
        extras = [
            p
            for p in f.parent.iterdir()
            if p.is_file()
            and p.suffix.lower()
            not in {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts"}
        ]
        for src in extras:
            try:
                dst = out.parent / src.name
                shutil.copy2(src, dst)
                self.log.emit(f"  copied {src.name}")
            except OSError as e:
                self.log.emit(f"  ⚠ failed to copy {src.name}: {e}")

    def _cleanup_partial(self, out: Path):
        """Remove partial output file from a failed/cancelled encode."""
        try:
            if out.exists():
                out.unlink()
                self.log.emit(f"  Removed partial file: {out.name}")
        except OSError:
            pass

    def _trash_file(self, path: Path):
        """Move file to system trash (macOS) or delete on other platforms."""
        try:
            if platform.system() == "Darwin":
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "Finder" to delete POSIX file "{path}"'],
                    capture_output=True, timeout=10,
                )
                self.log.emit(f"  Moved to Bin: {path.name}")
            else:
                path.unlink()
                self.log.emit(f"  Deleted: {path.name}")
        except Exception as e:
            self.log.emit(f"  ⚠ Could not remove {path.name}: {e}")
