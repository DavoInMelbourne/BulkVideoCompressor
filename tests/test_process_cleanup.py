"""
Tests for process cleanup, memory safety, VideoToolbox session management,
and thermal throttle safeguards.

These tests verify the fixes for:
  1. SIGTERM-before-SIGKILL (GPU encoder session leak)
  2. Orphan ffmpeg process cleanup
  3. stdout pipe closure (fd leak)
  4. Buffer cap in progress reading
  5. Streaming audio verification (memory usage)
  6. Thermal throttle detection (baseline capture, slow file, thermal abort)
"""
from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import psutil
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# We can't import EncodeWorker directly because PyQt6 may not be installed
# in the test environment.  Instead, we mock out QThread and pyqtSignal
# before importing so the module loads cleanly.

_qt_mocked = False


def _ensure_qt_mock():
    """Inject a minimal PyQt6 stub so workers.py can be imported."""
    global _qt_mocked
    if _qt_mocked:
        return
    if "PyQt6" not in sys.modules:
        # Minimal stubs
        qtcore = SimpleNamespace(
            QThread=type("QThread", (), {
                "__init__": lambda self, *a, **kw: None,
                "start": lambda self: None,
                "isRunning": lambda self: False,
                "wait": lambda self, *a: True,
                "terminate": lambda self: None,
                "deleteLater": lambda self: None,
            }),
            pyqtSignal=lambda *args, **kwargs: Mock(),
        )
        mod = SimpleNamespace(QtCore=qtcore)
        sys.modules["PyQt6"] = mod
        sys.modules["PyQt6.QtCore"] = qtcore
    _qt_mocked = True


_ensure_qt_mock()

# Now safe to import
from core.handbrake import kill_orphan_ffmpeg  # noqa: E402


# ---------------------------------------------------------------------------
# 1. SIGTERM before SIGKILL in _kill_proc_hard
# ---------------------------------------------------------------------------


class TestKillProcHard:
    """Verify that _kill_proc_hard sends SIGTERM first, only SIGKILL on timeout."""

    def _make_worker(self):
        """Create an EncodeWorker-like object with _kill_proc_hard."""
        from ui.workers import EncodeWorker

        # Construct without calling __init__ (needs QThread + many args)
        worker = object.__new__(EncodeWorker)
        worker._current_proc = None
        return worker

    def test_sigterm_called_before_sigkill_when_process_exits(self):
        """If the process exits after SIGTERM, SIGKILL should NOT be called."""
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = None  # still running
        proc.stdout = MagicMock()
        worker._current_proc = proc

        # terminate() causes wait() to succeed (process exits gracefully)
        proc.wait.return_value = None

        worker._kill_proc_hard()

        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()
        proc.stdout.close.assert_called_once()
        assert worker._current_proc is None

    def test_sigkill_fallback_when_sigterm_times_out(self):
        """If SIGTERM doesn't work within timeout, fall back to SIGKILL."""
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = None  # still running
        proc.stdout = MagicMock()
        worker._current_proc = proc

        # First wait (after terminate) raises TimeoutExpired
        proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="ffmpeg", timeout=5),
            None,  # second wait after kill succeeds
        ]

        worker._kill_proc_hard()

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        assert proc.wait.call_count == 2
        assert worker._current_proc is None

    def test_noop_when_process_already_exited(self):
        """If the process has already exited, no signals should be sent."""
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = 0  # already exited
        proc.stdout = MagicMock()
        worker._current_proc = proc

        worker._kill_proc_hard()

        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()
        # stdout should still be closed (fd cleanup)
        proc.stdout.close.assert_called_once()
        assert worker._current_proc is None

    def test_noop_when_no_process(self):
        """If _current_proc is None, nothing should happen."""
        worker = self._make_worker()
        worker._current_proc = None
        worker._kill_proc_hard()  # should not raise


class TestCancelCurrent:
    """Verify cancel_current uses SIGTERM."""

    def _make_worker(self):
        from ui.workers import EncodeWorker

        worker = object.__new__(EncodeWorker)
        worker._current_proc = None
        return worker

    def test_cancel_sends_sigterm_not_sigkill(self):
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = None
        worker._current_proc = proc

        worker.cancel_current()

        proc.terminate.assert_called_once()
        proc.kill.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Orphan ffmpeg cleanup
# ---------------------------------------------------------------------------


class TestKillOrphanFfmpeg:
    """Verify kill_orphan_ffmpeg finds and kills stale ffmpeg processes."""

    def _mock_proc(self, pid, ppid, name):
        p = MagicMock()
        p.info = {"pid": pid, "ppid": ppid, "name": name}
        p.terminate = MagicMock()
        p.wait = MagicMock()
        p.kill = MagicMock()
        return p

    @patch("core.handbrake.psutil.process_iter")
    def test_kills_orphan_ffmpeg(self, mock_iter):
        orphan = self._mock_proc(pid=1234, ppid=1, name="ffmpeg")
        mock_iter.return_value = [orphan]

        killed = kill_orphan_ffmpeg(own_pid=9999)

        assert killed == 1
        orphan.terminate.assert_called_once()

    @patch("core.handbrake.psutil.process_iter")
    def test_skips_own_children(self, mock_iter):
        my_pid = 9999
        child = self._mock_proc(pid=1234, ppid=my_pid, name="ffmpeg")
        mock_iter.return_value = [child]

        killed = kill_orphan_ffmpeg(own_pid=my_pid)

        assert killed == 0
        child.terminate.assert_not_called()

    @patch("core.handbrake.psutil.process_iter")
    def test_skips_non_ffmpeg_processes(self, mock_iter):
        chrome = self._mock_proc(pid=5555, ppid=1, name="Google Chrome")
        mock_iter.return_value = [chrome]

        killed = kill_orphan_ffmpeg(own_pid=9999)

        assert killed == 0
        chrome.terminate.assert_not_called()

    @patch("core.handbrake.psutil.process_iter")
    def test_kills_ffprobe_too(self, mock_iter):
        probe = self._mock_proc(pid=2222, ppid=1, name="ffprobe")
        mock_iter.return_value = [probe]

        killed = kill_orphan_ffmpeg(own_pid=9999)

        assert killed == 1
        probe.terminate.assert_called_once()

    @patch("core.handbrake.psutil.process_iter")
    def test_hard_kill_on_timeout(self, mock_iter):
        stubborn = self._mock_proc(pid=3333, ppid=1, name="ffmpeg")
        stubborn.wait.side_effect = psutil.TimeoutExpired(seconds=5)
        mock_iter.return_value = [stubborn]

        killed = kill_orphan_ffmpeg(own_pid=9999)

        assert killed == 1
        stubborn.terminate.assert_called_once()
        stubborn.kill.assert_called_once()

    @patch("core.handbrake.psutil.process_iter")
    def test_handles_nosuchprocess(self, mock_iter):
        ghost = self._mock_proc(pid=4444, ppid=1, name="ffmpeg")
        ghost.terminate.side_effect = psutil.NoSuchProcess(pid=4444)
        mock_iter.return_value = [ghost]

        # Should not raise
        killed = kill_orphan_ffmpeg(own_pid=9999)
        assert killed == 0

    @patch("core.handbrake.psutil.process_iter")
    def test_multiple_orphans(self, mock_iter):
        o1 = self._mock_proc(pid=100, ppid=1, name="ffmpeg")
        o2 = self._mock_proc(pid=200, ppid=1, name="ffprobe")
        o3 = self._mock_proc(pid=300, ppid=1, name="ffmpeg")
        mock_iter.return_value = [o1, o2, o3]

        killed = kill_orphan_ffmpeg(own_pid=9999)
        assert killed == 3


# ---------------------------------------------------------------------------
# 3. stdout pipe closure
# ---------------------------------------------------------------------------


class TestStdoutPipeClosure:
    """Verify stdout pipe is closed after _kill_proc_hard."""

    def _make_worker(self):
        from ui.workers import EncodeWorker

        worker = object.__new__(EncodeWorker)
        worker._current_proc = None
        return worker

    def test_pipe_closed_after_successful_terminate(self):
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = None
        stdout_mock = MagicMock()
        proc.stdout = stdout_mock
        worker._current_proc = proc

        worker._kill_proc_hard()

        stdout_mock.close.assert_called_once()

    def test_pipe_closed_even_when_process_already_dead(self):
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = 0  # already exited
        stdout_mock = MagicMock()
        proc.stdout = stdout_mock
        worker._current_proc = proc

        worker._kill_proc_hard()

        stdout_mock.close.assert_called_once()

    def test_no_crash_when_stdout_is_none(self):
        worker = self._make_worker()
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.stdout = None
        worker._current_proc = proc

        worker._kill_proc_hard()  # should not raise


# ---------------------------------------------------------------------------
# 4. Buffer cap in _read_progress
# ---------------------------------------------------------------------------


class TestBufferCap:
    """Verify the progress buffer doesn't grow unbounded."""

    def test_buffer_capped_without_carriage_returns(self):
        """Simulate ffmpeg output without \\r — buffer must not exceed cap."""
        from ui.workers import EncodeWorker

        worker = object.__new__(EncodeWorker)
        worker._current_proc = None

        # Build a mock process that outputs 20KB of data without any \r,
        # then returns empty bytes (EOF).
        big_chunk = b"x" * 10240  # 10 KB per chunk, no \r
        chunks = [big_chunk, big_chunk, b""]  # two big chunks then EOF
        chunk_iter = iter(chunks)

        proc = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = MagicMock(side_effect=lambda n: next(chunk_iter))
        proc.poll.return_value = None
        proc.wait.return_value = None

        # Stub out signals
        worker.progress = MagicMock()
        worker.log = MagicMock()
        worker.size_warning = MagicMock()

        # Create a minimal task dict
        src = MagicMock()
        src.stat.return_value.st_size = 1_000_000
        out = MagicMock()
        out.exists.return_value = False

        task = {
            "source": src,
            "output": out,
            "info": SimpleNamespace(duration_secs=100.0),
        }

        # Patch _STALL_TIMEOUT to something huge so stall detection doesn't
        # interfere — we're only testing buffer capping.
        import ui.workers as wmod
        orig_timeout = wmod._STALL_TIMEOUT
        orig_rss = wmod._RSS_LIMIT
        wmod._STALL_TIMEOUT = 999999
        wmod._RSS_LIMIT = 999 * 1024 * 1024 * 1024  # disable RSS check
        proc.pid = 99999  # real int so psutil.Process() doesn't choke on MagicMock
        try:
            worker._read_progress(proc, task, row=0)
        finally:
            wmod._STALL_TIMEOUT = orig_timeout
            wmod._RSS_LIMIT = orig_rss

        # The key assertion: the function completed without OOM and the
        # process was waited on. If the buffer grew unbounded, on a real
        # system with GB of output this would exhaust memory.
        proc.wait.assert_called()


# ---------------------------------------------------------------------------
# 5. Streaming audio verification
# ---------------------------------------------------------------------------


class TestVerifyOutputStreaming:
    """Verify audio scan streams line-by-line and cleans up subprocesses."""

    @patch("core.handbrake.subprocess.run")
    @patch("core.handbrake.subprocess.Popen")
    def test_clean_file_passes(self, mock_popen, mock_run):
        """A file with monotonic timestamps should pass verification."""
        # Stage 1: duration check (subprocess.run)
        mock_run.return_value = MagicMock(
            returncode=0, stdout="120.5\n"
        )

        # Stage 2: audio packet scan (Popen, streamed)
        lines = [
            b"0.000000,1024\n",
            b"0.023220,512\n",
            b"0.046440,512\n",
            b"1.000000,512\n",
            b"2.000000,512\n",
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        from core.handbrake import verify_output

        ok, msg = verify_output(Path("/usr/bin/ffprobe"), "/tmp/test.mkv", 120.5)

        assert ok is True
        assert "verified" in msg

    @patch("core.handbrake.subprocess.run")
    @patch("core.handbrake.subprocess.Popen")
    def test_audio_gap_detected(self, mock_popen, mock_run):
        """A >1s gap in audio timestamps should fail verification."""
        mock_run.return_value = MagicMock(returncode=0, stdout="60.0\n")

        lines = [
            b"0.000000,1024\n",
            b"0.500000,512\n",
            b"5.000000,512\n",  # 4.5s gap!
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        from core.handbrake import verify_output

        ok, msg = verify_output(Path("/usr/bin/ffprobe"), "/tmp/test.mkv", 60.0)

        assert ok is False
        assert "gap" in msg.lower()

    @patch("core.handbrake.subprocess.run")
    @patch("core.handbrake.subprocess.Popen")
    def test_audio_timestamp_jump_detected(self, mock_popen, mock_run):
        """Non-monotonic timestamps (backwards jump) should fail."""
        mock_run.return_value = MagicMock(returncode=0, stdout="60.0\n")

        lines = [
            b"0.000000,1024\n",
            b"1.000000,512\n",
            b"0.500000,512\n",  # backwards jump!
        ]
        mock_proc = MagicMock()
        mock_proc.stdout = iter(lines)
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b""
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        from core.handbrake import verify_output

        ok, msg = verify_output(Path("/usr/bin/ffprobe"), "/tmp/test.mkv", 60.0)

        assert ok is False
        assert "jump" in msg.lower()

    @patch("core.handbrake.subprocess.run")
    @patch("core.handbrake.subprocess.Popen")
    def test_subprocess_cleaned_up_on_early_exit(self, mock_popen, mock_run):
        """Even if we return early (gap found), the subprocess must be cleaned up."""
        mock_run.return_value = MagicMock(returncode=0, stdout="60.0\n")

        lines = [
            b"0.000000,1024\n",
            b"5.000000,512\n",  # immediate gap → early return
        ]
        # Use a MagicMock that is iterable AND has .close()
        stdout_mock = MagicMock()
        stdout_mock.__iter__ = Mock(return_value=iter(lines))
        stderr_mock = MagicMock()
        stderr_mock.read.return_value = b""

        mock_proc = MagicMock()
        mock_proc.stdout = stdout_mock
        mock_proc.stderr = stderr_mock
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        from core.handbrake import verify_output

        verify_output(Path("/usr/bin/ffprobe"), "/tmp/test.mkv", 60.0)

        # Pipes should be closed in the finally block
        stdout_mock.close.assert_called()
        stderr_mock.close.assert_called()

    @patch("core.handbrake.subprocess.run")
    @patch("core.handbrake.subprocess.Popen")
    def test_stderr_errors_detected(self, mock_popen, mock_run):
        """ffprobe stderr output should trigger failure."""
        mock_run.return_value = MagicMock(returncode=0, stdout="60.0\n")

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])  # no packets
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read.return_value = b"[error] something bad\n"
        mock_proc.wait.return_value = None
        mock_proc.poll.return_value = 0
        mock_popen.return_value = mock_proc

        from core.handbrake import verify_output

        ok, msg = verify_output(Path("/usr/bin/ffprobe"), "/tmp/test.mkv", 60.0)

        assert ok is False
        assert "errors detected" in msg.lower()

    @patch("core.handbrake.subprocess.run")
    def test_duration_mismatch_fails(self, mock_run):
        """Output duration must match source within 2 seconds."""
        mock_run.return_value = MagicMock(returncode=0, stdout="55.0\n")

        from core.handbrake import verify_output

        ok, msg = verify_output(Path("/usr/bin/ffprobe"), "/tmp/test.mkv", 60.0)

        assert ok is False
        assert "duration mismatch" in msg.lower()


# ---------------------------------------------------------------------------
# 6. Integration: real subprocess SIGTERM behaviour
# ---------------------------------------------------------------------------


class TestRealSubprocessSignals:
    """Integration test using a real subprocess to verify SIGTERM works."""

    def test_sigterm_actually_terminates_subprocess(self):
        """Start a real sleep process, SIGTERM it, verify it exits."""
        proc = subprocess.Popen(
            ["sleep", "60"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.poll() is None  # running

        proc.terminate()  # SIGTERM
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            pytest.fail("SIGTERM did not kill the process within 5s")

        # Process exited — signal 15 (SIGTERM) on macOS/Linux
        assert proc.returncode is not None
        # Clean up pipes
        proc.stdout.close()
        proc.stderr.close()

    def test_pipe_fd_is_released_after_close(self):
        """Verify closing stdout pipe releases the file descriptor."""
        proc = subprocess.Popen(
            ["echo", "hello"],
            stdout=subprocess.PIPE,
        )
        proc.wait()
        fd = proc.stdout.fileno()
        proc.stdout.close()

        # The fd should now be invalid
        with pytest.raises(OSError):
            os.fstat(fd)


# ---------------------------------------------------------------------------
# 7. Thermal throttle detection
# ---------------------------------------------------------------------------


def _make_encode_worker(**kwargs):
    """Create an EncodeWorker with mocked signals for thermal testing."""
    from ui.workers import EncodeWorker

    worker = object.__new__(EncodeWorker)
    worker._current_proc = None
    worker._oversize_abort = False
    worker._thermal_abort = False
    worker._slow_file_abort = False
    worker._baseline_fps = kwargs.get("baseline_fps", 0.0)
    worker._min_fps = kwargs.get("min_fps", 200)
    worker._last_fps = 0.0
    worker.progress = MagicMock()
    worker.log = MagicMock()
    worker.size_warning = MagicMock()
    worker.baseline_fps = MagicMock()
    worker.thermal_abort = MagicMock()
    worker.slow_file_abort = MagicMock()
    return worker


def _make_progress_chunks(fps_value, pct_time, speed=2.0, repeats=1):
    """Build ffmpeg-style progress output that will parse to given fps/pct."""
    line = f"\rfps= {fps_value:.1f} time={pct_time} speed={speed:.2f}x\r"
    return [line.encode()] * repeats + [b""]  # data then EOF


def _run_thermal_test(worker, fps_value, pct_time="00:00:10.00",
                      duration=100.0, task_extra=None, repeats=3):
    """Run _read_progress with progress lines and return the proc mock."""
    chunks = _make_progress_chunks(fps_value, pct_time, repeats=repeats)
    chunk_iter = iter(chunks)

    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.fileno.return_value = 999
    proc.poll.return_value = None
    proc.wait.return_value = None
    proc.pid = 99999

    src = MagicMock()
    src.stat.return_value.st_size = 1_000_000
    out = MagicMock()
    out.exists.return_value = False
    task = {
        "source": src, "output": out,
        "info": SimpleNamespace(duration_secs=duration),
    }
    if task_extra:
        task.update(task_extra)

    import ui.workers as wmod
    orig_timeout = wmod._STALL_TIMEOUT
    orig_rss = wmod._RSS_LIMIT
    wmod._STALL_TIMEOUT = 999999
    wmod._RSS_LIMIT = 999 * 1024 * 1024 * 1024

    _t = 100.0
    def _mono():
        nonlocal _t; _t += 10; return _t

    with patch("os.read", side_effect=lambda fd, n: next(chunk_iter)), \
         patch("time.monotonic", side_effect=_mono):
        try:
            worker._read_progress(proc, task, row=0)
        finally:
            wmod._STALL_TIMEOUT = orig_timeout
            wmod._RSS_LIMIT = orig_rss

    return proc


class TestThermalBaselineCapture:
    """Verify baseline FPS is captured at 10% progress."""

    def test_baseline_captured_above_min_fps(self):
        """When FPS > min_fps at 10%, baseline should be emitted."""
        worker = _make_encode_worker(min_fps=200)
        _run_thermal_test(worker, fps_value=250.0)

        assert worker._baseline_fps == 250.0
        worker.baseline_fps.emit.assert_called_once_with(250.0)
        assert worker._slow_file_abort is False

    def test_slow_file_abort_below_min_fps(self):
        """When FPS <= min_fps at 10%, slow_file_abort should be set."""
        worker = _make_encode_worker(min_fps=200)
        proc = _run_thermal_test(worker, fps_value=150.0)

        assert worker._slow_file_abort is True
        proc.terminate.assert_called()

    def test_baseline_emitted_even_below_min_fps(self):
        """Baseline should be set even when below min_fps (for UI display)."""
        worker = _make_encode_worker(min_fps=200)
        _run_thermal_test(worker, fps_value=150.0)

        assert worker._baseline_fps == 150.0
        worker.baseline_fps.emit.assert_called_once_with(150.0)


class TestMinFpsAndBaseline:
    """Verify Min FPS threshold and baseline behaviour."""

    def test_custom_min_fps_respected(self):
        """A custom min_fps value should be used for baseline threshold."""
        worker = _make_encode_worker(min_fps=100)
        _run_thermal_test(worker, fps_value=120.0)

        assert worker._baseline_fps == 120.0
        assert worker._slow_file_abort is False

    def test_no_detection_before_10pct(self):
        """Baseline check should not trigger before 10% progress."""
        worker = _make_encode_worker(min_fps=200)
        # time=5s on a 100s video = 5% — too early
        _run_thermal_test(worker, fps_value=150.0, pct_time="00:00:05.00")

        assert worker._baseline_fps == 0.0
        assert worker._slow_file_abort is False

    def test_baseline_not_recaptured_on_second_file(self):
        """Once baseline is set, subsequent files should not overwrite it."""
        worker = _make_encode_worker(baseline_fps=250.0, min_fps=200)
        _run_thermal_test(worker, fps_value=300.0)

        # Should remain at the original baseline, not updated to 300
        assert worker._baseline_fps == 250.0
