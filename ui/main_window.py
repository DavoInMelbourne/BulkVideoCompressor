from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QMainWindow, QProgressBar, QLabel, QPushButton, QWidget

from ui.window.constants import *  # noqa: F401,F403 — re-exports PRESETS + DEFAULT_* constants
from ui.window.build_ui import BuildUIMixin  # also pulls in SettingsTabMixin, QueueTabMixin
from ui.window.queue import QueueMixin
from ui.window.handlers import HandlersMixin
from ui.window.post_process import PostProcessMixin
from ui.window.prefs import PrefsMixin
from ui.workers import EncodeWorker, ProbeWorker


class MainWindow(BuildUIMixin, QueueMixin, HandlersMixin, PostProcessMixin, PrefsMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bulk Video Compressor")
        self.setMinimumWidth(720)
        self.setMinimumHeight(600)
        self._probe_worker: Optional[ProbeWorker] = None
        self._encode_worker: Optional[EncodeWorker] = None
        self._pending_tasks: list = []
        self._encoding_active: bool = False
        self._cancelled: set = set()
        self._copied_dirs: set = set()
        self._queued_sources: set = set()
        self._next_row: int = 0
        self._cli_path: Optional[Path] = None
        self._ffprobe_path: Optional[Path] = None
        self._encoder: str = "x265"
        self._encoder_preset: str = "medium"
        self._tasks_by_id: dict = {}
        self._progress_bars: list[QProgressBar] = []
        self._progress_labels: list[QLabel] = []
        self._delete_btns: list[QPushButton] = []
        self._status_labels: list[QLabel] = []
        self._row_task_ids: list[int] = []
        self._row_widgets: list[QWidget] = []
        self._completed_rows: set[int] = set()
        self._baseline_fps: float = 0.0
        self._cooling_down: bool = False
        self._caffeinate_proc: Optional[subprocess.Popen] = None
        self._files_since_cooldown: int = 0
        self._total_cooldown_secs: int = 0
        self._problem_file_count: int = 0
        self._directory_results: dict[Path, dict] = {}  # dir -> {"total": int, "success": set, "failed": set}
        self._build_ui()
        self._auto_detect()
        self._load_prefs()

    def _log(self, text: str):
        self.log_edit.append(text)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )

    def closeEvent(self, event):
        self._save_prefs()
        self._stop_caffeinate()
        if self._encode_worker and self._encode_worker.isRunning():
            self._encode_worker.cancel_current()
            if not self._encode_worker.wait(3000):
                self._encode_worker.terminate()
                self._encode_worker.wait(2000)
        event.accept()
