from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.handbrake import find_ffmpeg, find_ffprobe, kill_orphan_ffmpeg
from core.languages import Language
from ui.review_dialog import ReviewDialog
from ui.workers import EncodeWorker, ProbeWorker

# (encoder, encoder_preset, default_rf)
PRESETS: dict[str, tuple[str, str, float]] = {
    "Fast H.264 (Hardware)": ("h264_videotoolbox", "", 65.0),
    "Fast H.265 (Hardware)": ("hevc_videotoolbox", "", 82.0),
    "Fast H.264": ("x264", "fast", 22.0),
    "Balanced H.265": ("x265", "medium", 18.0),
    "Quality H.265 12-bit": ("x265_12bit", "medium", 20.0),  # RF 20 = excellent quality
    "Quality AV1": ("av1", "4", 30.0),
}
DEFAULT_PRESET = "Quality H.265 12-bit"
DEFAULT_PRESET_4K = "Fast H.265 (Hardware)"
DEFAULT_RF_4K = 55.0


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
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

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        about_action = QAction("About BVC", self)
        about_action.triggered.connect(self._show_about)
        self.menuBar().addMenu("BulkVideoCompressor").addAction(about_action)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        root.addWidget(
            self._dir_group(
                "Source Directory",
                "source_edit",
                self._browse_source,
                default="",
            )
        )
        root.addWidget(
            self._dir_group(
                "Output Directory",
                "output_edit",
                self._browse_output,
                default="",
            )
        )

        # Options
        opt = QGroupBox("Encoding Options")
        ol = QHBoxLayout(opt)
        ol.addWidget(QLabel("1080p & below:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.setCurrentText(DEFAULT_PRESET)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        ol.addWidget(self.preset_combo)
        self.rf_spin = QDoubleSpinBox()
        self.rf_spin.setRange(0, 100)
        self.rf_spin.setValue(PRESETS[DEFAULT_PRESET][2])
        self.rf_spin.setSingleStep(0.5)
        self.rf_spin.setDecimals(1)
        self.rf_spin.setToolTip(
            "Software encoders (x264/x265/AV1): lower = better quality\n"
            "Hardware encoders (VideoToolbox): higher = better quality"
        )
        ol.addWidget(self.rf_spin)
        self.rf_hint_label = QLabel()
        self.rf_hint_label.setStyleSheet("color: #888; font-size: 11px;")
        ol.addWidget(self.rf_hint_label)
        ol.addSpacing(16)
        ol.addWidget(QLabel("4K:"))
        self.preset_4k_combo = QComboBox()
        self.preset_4k_combo.addItems(list(PRESETS.keys()))
        self.preset_4k_combo.setCurrentText(DEFAULT_PRESET_4K)
        self.preset_4k_combo.currentTextChanged.connect(self._on_4k_preset_changed)
        ol.addWidget(self.preset_4k_combo)
        self.rf_4k_spin = QDoubleSpinBox()
        self.rf_4k_spin.setRange(0, 100)
        self.rf_4k_spin.setValue(DEFAULT_RF_4K)
        self.rf_4k_spin.setSingleStep(0.5)
        self.rf_4k_spin.setDecimals(1)
        self.rf_4k_spin.setToolTip(
            "RF quality for 4K files.\n"
            "Software encoders (x264/x265/AV1): lower = better quality\n"
            "Hardware encoders (VideoToolbox): higher = better quality"
        )
        ol.addWidget(self.rf_4k_spin)
        self.rf_4k_hint_label = QLabel()
        self.rf_4k_hint_label.setStyleSheet("color: #888; font-size: 11px;")
        ol.addWidget(self.rf_4k_hint_label)
        ol.addSpacing(12)
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setFixedHeight(26)
        reset_btn.setToolTip("Reset encoding options to default settings")
        reset_btn.clicked.connect(self._on_reset_defaults)
        ol.addWidget(reset_btn)
        ol.addStretch()
        root.addWidget(opt)
        # Initialise hint labels to match the default presets
        self._update_rf_hint(DEFAULT_PRESET, self.rf_hint_label)
        self._update_rf_hint(DEFAULT_PRESET_4K, self.rf_4k_hint_label)

        # Smart Skip
        skip_grp = QGroupBox("Smart Skip (hevc / av1 already compressed)")
        sl = QHBoxLayout(skip_grp)
        sl.addWidget(QLabel("Skip 4K if under:"))
        self.skip_threshold_4k_spin = QDoubleSpinBox()
        self.skip_threshold_4k_spin.setRange(0, 200)
        self.skip_threshold_4k_spin.setValue(20.0)
        self.skip_threshold_4k_spin.setSingleStep(1.0)
        self.skip_threshold_4k_spin.setDecimals(1)
        self.skip_threshold_4k_spin.setSuffix(" GB")
        self.skip_threshold_4k_spin.setToolTip("4K hevc/av1 files smaller than this are skipped (already well compressed).")
        sl.addWidget(self.skip_threshold_4k_spin)
        sl.addSpacing(20)
        sl.addWidget(QLabel("Skip 1080p & below if under:"))
        self.skip_threshold_1080p_spin = QDoubleSpinBox()
        self.skip_threshold_1080p_spin.setRange(0, 200)
        self.skip_threshold_1080p_spin.setValue(4.0)
        self.skip_threshold_1080p_spin.setSingleStep(0.5)
        self.skip_threshold_1080p_spin.setDecimals(1)
        self.skip_threshold_1080p_spin.setSuffix(" GB")
        self.skip_threshold_1080p_spin.setToolTip("1080p and below hevc/av1 files smaller than this are skipped.")
        sl.addWidget(self.skip_threshold_1080p_spin)
        sl.addStretch()
        root.addWidget(skip_grp)

        # Language Preferences
        lang = QGroupBox("Language Preferences")
        ll = QHBoxLayout(lang)
        _lang_labels = Language.labels()

        ll.addWidget(QLabel("Audio:"))
        self.audio_language_combo = QComboBox()
        self.audio_language_combo.addItems(_lang_labels)
        self.audio_language_combo.setCurrentText("Original Language")
        self.audio_language_combo.setToolTip(
            "Preferred audio track language.\n"
            "For non-English selections the first non-English track in that language is chosen."
        )
        ll.addWidget(self.audio_language_combo)
        ll.addSpacing(20)

        ll.addWidget(QLabel("Subtitles:"))
        self.subtitle_language_combo = QComboBox()
        self.subtitle_language_combo.addItems(_lang_labels)
        self.subtitle_language_combo.setCurrentText("English")
        self.subtitle_language_combo.setToolTip("Preferred subtitle language.")
        ll.addWidget(self.subtitle_language_combo)
        ll.addSpacing(20)

        ll.addWidget(QLabel("Fallback:"))
        self.fallback_language_combo = QComboBox()
        self.fallback_language_combo.addItems(_lang_labels)
        self.fallback_language_combo.setCurrentText("English")
        self.fallback_language_combo.setToolTip(
            "Used for both audio and subtitles when the preferred language is not found in the file."
        )
        ll.addWidget(self.fallback_language_combo)
        ll.addSpacing(20)

        self.prioritise_dts_checkbox = QCheckBox("Prioritise DTS")
        self.prioritise_dts_checkbox.setChecked(True)
        self.prioritise_dts_checkbox.setToolTip("Prefer DTS/TrueHD audio tracks over other codecs")
        ll.addWidget(self.prioritise_dts_checkbox)
        ll.addStretch()
        root.addWidget(lang)

        # Post Processing
        post = QGroupBox("Post Processing")
        pl = QHBoxLayout(post)
        pl.addWidget(QLabel("Success suffix:"))
        self.file_success_suffix = QLineEdit()
        self.file_success_suffix.setFixedWidth(80)
        self.file_success_suffix.setText("Done")
        self.file_success_suffix.setToolTip("Suffix added to folder/file on successful compress. Leave empty for no rename.")
        pl.addWidget(self.file_success_suffix)
        pl.addSpacing(20)
        pl.addWidget(QLabel("Problem suffix:"))
        self.file_problem_suffix = QLineEdit()
        self.file_problem_suffix.setFixedWidth(80)
        self.file_problem_suffix.setText("Check")
        self.file_problem_suffix.setToolTip("Suffix added to folder/file on failed compress. Leave empty for no rename.")
        pl.addWidget(self.file_problem_suffix)
        pl.addSpacing(20)
        pl.addWidget(QLabel("Skip suffix:"))
        self.file_skip_suffix = QLineEdit()
        self.file_skip_suffix.setFixedWidth(80)
        self.file_skip_suffix.setText("Skip")
        self.file_skip_suffix.setToolTip("Suffix added to folder/file when skipped (already efficient codec). Leave empty for no rename.")
        pl.addWidget(self.file_skip_suffix)
        pl.addSpacing(20)
        pl.addWidget(QLabel("Remux suffix:"))
        self.file_remux_suffix = QLineEdit()
        self.file_remux_suffix.setFixedWidth(80)
        self.file_remux_suffix.setText("Remux")
        self.file_remux_suffix.setToolTip("Suffix added to folder/file after a remux (stream copy with track selection). Leave empty for no rename.")
        pl.addWidget(self.file_remux_suffix)
        pl.addSpacing(20)
        pl.addWidget(QLabel("After success:"))
        self.delete_source_combo = QComboBox()
        self.delete_source_combo.addItems(["Keep", "Move to Bin", "Delete Permanently"])
        self.delete_source_combo.setCurrentText("Keep")
        self.delete_source_combo.setToolTip(
            "What to do with the source file/folder after a verified successful encode.\n"
            "Move to Bin is recommended — files can be recovered if something went wrong."
        )
        pl.addWidget(self.delete_source_combo)
        pl.addStretch()
        root.addWidget(post)

        # Thermal safeguards
        therm = QGroupBox("Thermal Safeguards")
        tl = QHBoxLayout(therm)
        tl.addWidget(QLabel("Min FPS:"))
        self.min_fps_spin = QSpinBox()
        self.min_fps_spin.setRange(10, 1000)
        self.min_fps_spin.setValue(80)
        self.min_fps_spin.setToolTip(
            "Minimum expected FPS at 10% progress.\n"
            "Files below this are flagged as problem files."
        )
        tl.addWidget(self.min_fps_spin)
        self._baseline_label = QLabel("")
        self._baseline_label.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 11px;")
        tl.addWidget(self._baseline_label)
        tl.addSpacing(20)
        tl.addWidget(QLabel("Cool every:"))
        self.cool_every_spin = QSpinBox()
        self.cool_every_spin.setRange(1, 200)
        self.cool_every_spin.setValue(10)
        self.cool_every_spin.setToolTip("Insert a proactive cooldown after this many files")
        self.cool_every_spin.setSuffix(" files")
        tl.addWidget(self.cool_every_spin)
        tl.addWidget(QLabel("for"))
        self.cool_mins_spin = QDoubleSpinBox()
        self.cool_mins_spin.setRange(0.5, 30.0)
        self.cool_mins_spin.setValue(2.0)
        self.cool_mins_spin.setSingleStep(0.5)
        self.cool_mins_spin.setDecimals(1)
        self.cool_mins_spin.setSuffix(" min")
        self.cool_mins_spin.setToolTip("Duration of proactive cooldown")
        tl.addWidget(self.cool_mins_spin)
        tl.addStretch()
        root.addWidget(therm)

        # CLI path
        cli_grp = QGroupBox("ffmpeg")
        cl = QHBoxLayout(cli_grp)
        cl.addWidget(QLabel("Path:"))
        self.hb_path_edit = QLineEdit()
        self.hb_path_edit.setPlaceholderText("Auto-detected — override if needed")
        cl.addWidget(self.hb_path_edit)
        b = QPushButton("Browse")
        b.setFixedWidth(80)
        b.clicked.connect(self._browse_cli)
        cl.addWidget(b)
        root.addWidget(cli_grp)

        # Buttons row
        btn_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan && Review")
        self.scan_btn.setFixedHeight(38)
        self.scan_btn.setStyleSheet(self._btn_style("#2980b9", "#3498db"))
        self.scan_btn.clicked.connect(self._on_scan)
        btn_row.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.setStyleSheet(self._btn_style("#c0392b", "#e74c3c"))
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.hide()
        btn_row.addWidget(self.stop_btn)

        self.clear_btn = QPushButton("Clear completed")
        self.clear_btn.setFixedHeight(38)
        self.clear_btn.setStyleSheet(self._btn_style("#7f8c8d", "#95a5a6"))
        self.clear_btn.clicked.connect(self._on_clear_completed)
        self.clear_btn.hide()
        btn_row.addWidget(self.clear_btn)
        root.addLayout(btn_row)

        # Progress area (scrollable)
        self.progress_widget = QWidget()
        self.progress_layout = QVBoxLayout(self.progress_widget)
        self.progress_layout.setSpacing(4)
        self.progress_layout.setContentsMargins(4, 4, 4, 4)
        self.progress_layout.addStretch()

        self.progress_scroll = QScrollArea()
        self.progress_scroll.setWidget(self.progress_widget)
        self.progress_scroll.setWidgetResizable(True)
        self.progress_scroll.setMinimumHeight(200)
        self.progress_scroll.hide()

        # Log
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(80)
        self.log_edit.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: monospace; font-size: 12px; }"
        )

        # Splitter keeps the two panels from overlapping when the window is resized
        self._bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        self._bottom_splitter.addWidget(self.progress_scroll)
        self._bottom_splitter.addWidget(self.log_edit)
        self._bottom_splitter.setStretchFactor(0, 3)  # progress gets 3/4
        self._bottom_splitter.setStretchFactor(1, 1)  # log gets 1/4
        root.addWidget(self._bottom_splitter)

    def _btn_style(self, normal, hover):
        return (
            f"QPushButton {{ background-color: {normal}; color: white; font-size: 13px; "
            "border-radius: 4px; } "
            f"QPushButton:hover {{ background-color: {hover}; }} "
            "QPushButton:disabled { background-color: #7f8c8d; }"
        )

    def _dir_group(self, title, attr_name, browse_fn, default="") -> QGroupBox:
        g = QGroupBox(title)
        row = QHBoxLayout(g)
        edit = QLineEdit()
        edit.setText(default) if default else edit.setPlaceholderText(
            f"Select {title.lower()}…"
        )
        setattr(self, attr_name, edit)
        row.addWidget(edit)
        btn = QPushButton("Browse")
        btn.setFixedWidth(80)
        btn.clicked.connect(browse_fn)
        row.addWidget(btn)
        return g

    @staticmethod
    def _rf_hint_text(preset_name: str) -> str:
        encoder, _, _ = PRESETS[preset_name]
        if "videotoolbox" in encoder:
            return "↑ higher = better qlty"
        return "↓ lower = better qlty"

    def _update_rf_hint(self, preset_name: str, label: QLabel):
        label.setText(self._rf_hint_text(preset_name))

    def _on_preset_changed(self, name: str):
        _, _, rf = PRESETS[name]
        self.rf_spin.setValue(rf)
        self._update_rf_hint(name, self.rf_hint_label)

    def _on_4k_preset_changed(self, name: str):
        _, _, rf = PRESETS[name]
        self.rf_4k_spin.setValue(rf)
        self._update_rf_hint(name, self.rf_4k_hint_label)

    def _on_reset_defaults(self):
        self.preset_combo.setCurrentText(DEFAULT_PRESET)
        self.rf_spin.setValue(PRESETS[DEFAULT_PRESET][2])
        self.preset_4k_combo.setCurrentText(DEFAULT_PRESET_4K)
        self.rf_4k_spin.setValue(DEFAULT_RF_4K)
        self._update_rf_hint(DEFAULT_PRESET, self.rf_hint_label)
        self._update_rf_hint(DEFAULT_PRESET_4K, self.rf_4k_hint_label)
        self.min_fps_spin.setValue(80)

    def _show_about(self):
        QMessageBox.about(
            self,
            "About Bulk Video Compressor",
            "<b>Bulk Video Compressor</b><br>"
            "by <a href='https://github.com/DavoInMelbourne'>DavoInMelbourne</a><br><br>"
            "Batch compress video libraries using ffmpeg.<br>"
            "Built for people who want to compress a library of movies or TV shows "
            "quickly without manually adding files to an encoder one by one.",
        )

    def _auto_detect(self):
        # Kill any orphan ffmpeg/ffprobe processes left from a previous
        # crash — they hold VideoToolbox GPU encoder slots and leak memory.
        orphans = kill_orphan_ffmpeg()
        if orphans:
            self._log(
                f"Killed {orphans} orphan ffmpeg process(es) from a previous run."
            )

        cli = find_ffmpeg()
        if cli:
            self.hb_path_edit.setText(str(cli))
            self._log(f"Found ffmpeg: {cli}")
        else:
            self._log("ffmpeg not found — please set path manually.")

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------

    def _browse_source(self):
        d = QFileDialog.getExistingDirectory(self, "Select Source Directory")
        if d:
            self.source_edit.setText(d)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_edit.setText(d)

    def _browse_cli(self):
        p, _ = QFileDialog.getOpenFileName(self, "Locate HandBrakeCLI")
        if p:
            self.hb_path_edit.setText(p)

    # ------------------------------------------------------------------
    # Scan -> Review -> queue tasks
    # ------------------------------------------------------------------

    def _on_scan(self):
        source = self.source_edit.text().strip()
        output = self.output_edit.text().strip()
        if not source:
            QMessageBox.warning(
                self, "Missing Input", "Please select a source directory."
            )
            return
        if not output:
            QMessageBox.warning(
                self, "Missing Input", "Please select an output directory."
            )
            return
        if not Path(source).is_dir():
            QMessageBox.warning(
                self, "Invalid Path", "Source directory does not exist."
            )
            return

        if self._encoding_active:
            resp = QMessageBox.question(
                self,
                "Encoding In Progress",
                "Scanning while encoding is active may cause memory issues. "
                "Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.available < 2 * 1024 * 1024 * 1024:  # 2GB
                QMessageBox.warning(
                    self,
                    "Low Memory",
                    f"Only {mem.available // (1024**3)}GB RAM available. "
                    "Please free memory before scanning.",
                )
                return
        except ImportError:
            pass

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")
        self._log(f"Scanning {source}…")
        self._probe_worker = ProbeWorker(
            source_dir=source,
            output_dir=output,
            audio_language=Language.from_label(self.audio_language_combo.currentText()),
            subtitle_language=Language.from_label(self.subtitle_language_combo.currentText()),
            fallback_language=Language.from_label(self.fallback_language_combo.currentText()),
            prioritise_dts=self.prioritise_dts_checkbox.isChecked(),
        )
        self._probe_worker.log.connect(self._log)
        self._probe_worker.probed.connect(self._on_probed)
        self._probe_worker.failed.connect(self._on_probe_failed)
        self._probe_worker.start()

    def _on_probe_failed(self, msg):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan && Review")
        QMessageBox.critical(self, "Error", msg)

    def _on_probed(self, tasks: list):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan && Review")
        if not tasks:
            QMessageBox.warning(self, "Nothing found", "No files could be probed.")
            return

        # Assign per-task encoder based on resolution; flag files to skip
        encoder_std, encoder_preset_std, _ = PRESETS[self.preset_combo.currentText()]
        encoder_4k, encoder_preset_4k, _ = PRESETS[self.preset_4k_combo.currentText()]
        rf_std = self.rf_spin.value()
        rf_4k = self.rf_4k_spin.value()
        threshold_4k_bytes   = self.skip_threshold_4k_spin.value()   * 1_000_000_000
        threshold_1080p_bytes = self.skip_threshold_1080p_spin.value() * 1_000_000_000
        for t in tasks:
            info = t["info"]
            is_4k = info.height >= 2160 or info.width >= 3840
            if is_4k:
                t["encoder"] = encoder_4k
                t["encoder_preset"] = encoder_preset_4k
                t["rf"] = rf_4k
                threshold = threshold_4k_bytes
            else:
                t["encoder"] = encoder_std
                t["encoder_preset"] = encoder_preset_std
                t["rf"] = rf_std
                threshold = threshold_1080p_bytes
            codec = info.video_codec.lower()
            is_skip_candidate = (
                codec in ("hevc", "av1")
                and threshold > 0
                and info.file_size_bytes < threshold
            )
            if is_skip_candidate:
                t["skip"] = True
                # Determine if a remux is actually needed (streams would be dropped)
                # or if the file is already clean (true skip — just rename)
                needs_remux = (
                    len(info.audio_tracks) > 1
                    or len(t["subs"]) < len(info.subtitle_tracks)
                )
                if needs_remux:
                    t["encoder"] = "copy"
                    t["encoder_preset"] = ""
                    t["rf"] = 0
                else:
                    t["true_skip"] = True  # nothing to drop — rename only, no encode

        dlg = ReviewDialog(
            tasks, self.rf_spin.value(), self.preset_combo.currentText(), parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._log("Cancelled.\n")
            return

        cli_str = self.hb_path_edit.text().strip()
        cli_path = Path(cli_str) if cli_str else find_ffmpeg()
        if cli_path is None:
            QMessageBox.critical(self, "Error", "ffmpeg not found.")
            return

        self._enqueue_tasks(tasks, cli_path)

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _enqueue_tasks(self, tasks: list, cli_path: Path):
        if not self._encoding_active:
            # Clear old progress rows (leave the trailing stretch)
            while self.progress_layout.count() > 1:
                w = self.progress_layout.takeAt(0).widget()
                if w:
                    w.deleteLater()
            self._progress_bars = []
            self._progress_labels = []
            self._delete_btns = []
            self._status_labels = []
            self._row_task_ids = []
            self._row_widgets = []
            self._completed_rows = set()
            self._tasks_by_id = {}
            self._pending_tasks = []
            self._cancelled = set()
            self._copied_dirs = set()
            self._queued_sources = set()
            self._next_row = 0
            self._baseline_fps = 0.0
            self._cooling_down = False
            self._baseline_label.setText("")
            self._files_since_cooldown = 0
            self._total_cooldown_secs = 0
            self._problem_file_count = 0
            self._directory_results = {}
            self._cli_path = cli_path
            self._ffprobe_path = find_ffprobe(cli_path)
            self._encoder, self._encoder_preset, _ = PRESETS[
                self.preset_combo.currentText()
            ]

        source_root = Path(self.source_edit.text().strip())
        added = 0
        duplicates = 0
        for t in tasks:
            src = t["source"]
            if src in self._queued_sources:
                duplicates += 1
                continue
            self._queued_sources.add(src)
            self._tasks_by_id[t["id"]] = t
            self._add_progress_row(src.name, t["id"])
            row = self._next_row
            self._next_row += 1
            added += 1
            # Track files per source directory (for deferring multi-file dir operations)
            src_dir = src.parent
            if src_dir.resolve() != source_root.resolve():
                if src_dir not in self._directory_results:
                    self._directory_results[src_dir] = {
                        "total": 0, "done": set(), "success_count": 0, "failed_count": 0
                    }
                self._directory_results[src_dir]["total"] += 1

            if t.get("true_skip"):
                self._set_status(row, "Skipped", "#7f8c8d")
                self._completed_rows.add(row)
                if row < len(self._delete_btns):
                    self._delete_btns[row].setEnabled(True)
                out = t["output"]
                QTimer.singleShot(0, lambda r=row, s=src, sr=source_root, o=out: self._handle_true_skip(r, s, sr, o))
            else:
                self._pending_tasks.append((t, row))

        self.progress_scroll.show()
        msg = f"→ {added} file(s) added to queue."
        if duplicates:
            msg += f" ({duplicates} duplicate(s) skipped)"
        self._log(msg + "\n")

        if not self._encoding_active:
            self._encoding_active = True
            self._start_caffeinate()
            self.stop_btn.show()
            self.clear_btn.show()
            self._start_next_encode()

    def _start_next_encode(self):
        if self._cooling_down:
            return  # QTimer will call us when cooldown expires

        # Discard the finished worker so Python can reclaim its memory
        if self._encode_worker is not None:
            self._encode_worker.deleteLater()
            self._encode_worker = None
            self._files_since_cooldown += 1

        if not self._pending_tasks:
            self._encoding_active = False
            self._on_encode_finished()
            return

        # Proactive cooldown every N files
        cool_every = self.cool_every_spin.value()
        if self._files_since_cooldown >= cool_every:
            self._files_since_cooldown = 0
            cool_mins = self.cool_mins_spin.value()
            cool_ms = int(cool_mins * 60 * 1000)
            self._cooling_down = True
            self._total_cooldown_secs += int(cool_mins * 60)
            self._log(
                f"Proactive cooldown: {cool_mins:.1f} minutes "
                f"after {cool_every} files\n"
            )
            QTimer.singleShot(cool_ms, self._resume_after_cooldown)
            return

        t, row = self._pending_tasks.pop(0)
        self._encode_worker = EncodeWorker(
            task=t,
            row=row,
            cancelled=self._cancelled,
            copied_dirs=self._copied_dirs,
            cli_path=self._cli_path,
            ffprobe_path=self._ffprobe_path,
            rf=self.rf_spin.value(),
            encoder=self._encoder,
            encoder_preset=self._encoder_preset,
            baseline_fps=self._baseline_fps,
            min_fps=self.min_fps_spin.value(),
        )
        self._encode_worker.log.connect(self._log)
        self._encode_worker.progress.connect(self._on_progress)
        self._encode_worker.task_done.connect(self._on_task_done)
        self._encode_worker.verified.connect(self._on_verified)
        self._encode_worker.skipped.connect(self._on_skipped)
        self._encode_worker.size_warning.connect(self._on_size_warning)
        self._encode_worker.reverse_compression.connect(self._on_reverse_compression)
        self._encode_worker.crashed.connect(self._on_crashed)
        self._encode_worker.baseline_fps.connect(self._on_baseline_fps)
        self._encode_worker.slow_file_abort.connect(self._on_slow_file_abort)
        self._encode_worker.compression_done.connect(self._on_compression_done)
        self._encode_worker.finished.connect(self._start_next_encode)
        self._encode_worker.start()

    # ------------------------------------------------------------------
    # Progress row UI
    # ------------------------------------------------------------------

    def _add_progress_row(self, filename: str, task_id: int):
        row_widget = QWidget()
        rl = QHBoxLayout(row_widget)
        rl.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(filename)
        lbl.setFixedWidth(300)
        lbl.setToolTip(filename)
        rl.addWidget(lbl)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        rl.addWidget(bar)

        eta_lbl = QLabel("")
        eta_lbl.setFixedWidth(180)
        rl.addWidget(eta_lbl)

        status_lbl = QLabel("Waiting")
        status_lbl.setFixedWidth(130)
        status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_lbl.setStyleSheet(
            "QLabel { background: #555; color: #ccc; border-radius: 3px; "
            "padding: 2px 6px; font-size: 11px; }"
        )
        rl.addWidget(status_lbl)

        info_btn = QPushButton("ℹ")
        info_btn.setFixedWidth(28)
        info_btn.setFixedHeight(24)
        info_btn.setToolTip("Show encoding parameters")
        info_btn.setStyleSheet(
            "QPushButton { color: #2980b9; border: 1px solid #2980b9; border-radius: 3px; }"
            "QPushButton:hover { background: #2980b9; color: white; }"
        )
        info_btn.clicked.connect(lambda _, rid=task_id: self._on_show_info(rid))
        rl.addWidget(info_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedWidth(28)
        del_btn.setFixedHeight(24)
        del_btn.setToolTip("Remove from queue")
        del_btn.setStyleSheet(
            "QPushButton { color: #e74c3c; font-weight: bold; border: 1px solid #e74c3c; "
            "border-radius: 3px; } QPushButton:hover { background: #e74c3c; color: white; }"
            "QPushButton:disabled { color: #555; border-color: #555; }"
        )
        del_btn.clicked.connect(lambda _, rid=task_id: self._on_delete_task(rid))
        rl.addWidget(del_btn)

        # Insert before the trailing stretch
        self.progress_layout.insertWidget(self.progress_layout.count() - 1, row_widget)
        self._progress_bars.append(bar)
        self._progress_labels.append(eta_lbl)
        self._status_labels.append(status_lbl)
        self._delete_btns.append(del_btn)
        self._row_task_ids.append(task_id)
        self._row_widgets.append(row_widget)
        # Scroll to show the newly added row
        self.progress_scroll.verticalScrollBar().setValue(
            self.progress_scroll.verticalScrollBar().maximum()
        )

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_show_info(self, task_id: int):
        t = self._tasks_by_id.get(task_id)
        if not t:
            return
        info = t["info"]
        audio = t["audio"]
        subs = t["subs"]
        rf = t.get("rf", self.rf_spin.value())

        fps_str = f"{info.fps:.3f}".rstrip("0").rstrip(".")
        audio_str = (
            f"Track {audio.index} · {audio.language or '?'} · <b>Passthru</b>"
            if audio
            else "None"
        )
        sub_lines = []
        for s in subs:
            kind = "Forced" if s.forced else ("SDH" if s.sdh else "Regular")
            sub_lines.append(
                f"  Track {s.index} — {kind} [{s.language or '?'}]  (NOT burned in)"
            )

        msg = (
            f"<b>{t['source'].name}</b><br><br>"
            f"<b>Video:</b> {info.width}×{info.height} · {fps_str} fps · H.265 12-bit · RF {rf}<br><br>"
            f"<b>Audio:</b> {audio_str}<br><br>"
            f"<b>Subtitles:</b><br>{'<br>'.join(sub_lines) if sub_lines else 'None'}<br><br>"
            f"<b>Output:</b><br>{t['output']}"
        )
        box = QMessageBox(self)
        box.setWindowTitle("Encoding Parameters")
        box.setText(msg)
        box.exec()

    def _on_delete_task(self, task_id: int):
        if task_id in self._row_task_ids:
            row = self._row_task_ids.index(task_id)
            if row in self._completed_rows:
                # Row is done — just hide it
                self._row_widgets[row].hide()
                return
        # Still pending or encoding — cancel it
        self._cancelled.add(task_id)
        # Remove from pending list if not started yet
        self._pending_tasks[:] = [
            (t, r) for t, r in self._pending_tasks if t["id"] != task_id
        ]
        if (
            self._encode_worker
            and self._encode_worker.isRunning()
            and self._encode_worker._current_id == task_id
        ):
            self._encode_worker.cancel_current()
        if task_id in self._row_task_ids:
            row = self._row_task_ids.index(task_id)
            self._progress_bars[row].setValue(0)
            self._progress_labels[row].setText("")
            self._set_status(row, "Cancelled", "#7f8c8d")
            self._delete_btns[row].setEnabled(False)

    def _set_status(self, row: int, text: str, colour: str):
        if row < len(self._status_labels):
            self._status_labels[row].setText(text)
            self._status_labels[row].setStyleSheet(
                f"QLabel {{ background: {colour}; color: white; border-radius: 3px; "
                f"padding: 2px 6px; font-size: 11px; font-weight: bold; }}"
            )

    def _on_clear_completed(self):
        for row in self._completed_rows:
            if row < len(self._row_widgets):
                self._row_widgets[row].hide()

    def _on_size_warning(self, row: int):
        self._set_status(row, "⚠ Running large", "#e67e22")
        self._log(
            f"  ⚠ Row {row + 1}: output is tracking larger than source — check at 33%\n"
        )

    def _on_progress(self, row: int, pct: int, fps: float, eta: str):
        if row < len(self._progress_bars):
            self._progress_bars[row].setValue(pct)
            if pct == 0:
                self._set_status(row, "Encoding", "#2980b9")
            if eta:
                self._progress_labels[row].setText(f"{pct}%  {fps:.1f} fps  ETA {eta}")

    def _on_task_done(self, row: int, success: bool):
        if row < len(self._progress_bars):
            self._progress_bars[row].setValue(100 if success else 0)
            self._progress_labels[row].setText("")
            if success:
                self._set_status(row, "Scanning…", "#d35400")
            else:
                self._set_status(row, "Failed", "#c0392b")
                self._completed_rows.add(row)
                self._row_widgets[row].setStyleSheet(
                    "QWidget { background-color: rgba(192, 57, 43, 0.25); "
                    "border-left: 4px solid #c0392b; border-radius: 4px; }"
                )
                if row < len(self._delete_btns):
                    self._delete_btns[row].setEnabled(True)

    def _on_verified(self, row: int, ok: bool, msg: str):
        if row < len(self._status_labels):
            self._completed_rows.add(row)
            if ok:
                fps_tag = ""
                if "FFPS: " in msg:
                    fps_tag = f", {msg.rsplit('FFPS: ', 1)[1]} FFPS"
                self._set_status(row, f"✓ Safe to delete{fps_tag}", "#27ae60")
            else:
                self._set_status(row, "⚠ Keep original", "#c0392b")
            if row < len(self._delete_btns):
                self._delete_btns[row].setEnabled(True)

    def _on_reverse_compression(self, row: int, msg: str):
        if row < len(self._status_labels):
            self._completed_rows.add(row)
            self._set_status(row, "Reverse compression", "#8e44ad")
            self._progress_labels[row].setText(msg)
            self._row_widgets[row].setStyleSheet(
                "QWidget { background-color: rgba(142, 68, 173, 0.15); border-radius: 4px; }"
            )
            if row < len(self._delete_btns):
                self._delete_btns[row].setEnabled(True)

    def _on_crashed(self, row: int, error: str):
        """Mark the row with a red line and move on to the next file."""
        if row < len(self._status_labels):
            self._completed_rows.add(row)
            self._set_status(row, "ERROR", "#c0392b")
            self._progress_bars[row].setValue(0)
            self._progress_labels[row].setText(error[:80])
            self._row_widgets[row].setStyleSheet(
                "QWidget { background-color: rgba(192, 57, 43, 0.25); "
                "border-left: 4px solid #c0392b; border-radius: 4px; }"
            )
            if row < len(self._delete_btns):
                self._delete_btns[row].setEnabled(True)

    def _on_skipped(self, row: int):
        if row < len(self._status_labels):
            self._progress_labels[row].setText("")
            self._set_status(row, "Cancelled", "#7f8c8d")
            self._completed_rows.add(row)
            if row < len(self._delete_btns):
                    self._delete_btns[row].setEnabled(True)

    def _handle_true_skip(self, row: int, source_file: Path, source_root: Path, output_path: Path):
        """File needs no remux — copy to output dir and apply skip suffix."""
        skip_suffix = self.file_skip_suffix.text().strip()
        src_dir = source_file.parent
        dir_info = self._directory_results.get(src_dir)
        output_root = Path(self.output_edit.text().strip())
        output_dir = output_path.parent
        has_container = output_dir.resolve() != output_root.resolve()

        size_gb = source_file.stat().st_size / 1_000_000_000 if source_file.exists() else 0

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, output_path)
            self._log(f"  SKIP | {source_file.name} | already clean ({size_gb:.1f}GB) — copied to output\n")
        except Exception as e:
            self._log(f"  ⚠ SKIP copy failed for {source_file.name}: {e}\n")
            return

        # Copy non-video extras (NFO, artwork, subtitles etc.) from source dir,
        # same as the encode worker does. Use _copied_dirs to copy once per directory.
        src_dir = source_file.parent
        if src_dir not in self._copied_dirs:
            self._copied_dirs.add(src_dir)
            _video_exts = {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts"}
            for extra in src_dir.iterdir():
                if extra.is_file() and extra.suffix.lower() not in _video_exts:
                    try:
                        shutil.copy2(extra, output_path.parent / extra.name)
                        self._log(f"  copied {extra.name}")
                    except OSError as e:
                        self._log(f"  ⚠ could not copy {extra.name}: {e}")

        if dir_info is not None:
            dir_info["done"].add(source_file)
            dir_info.setdefault("skip_count", 0)
            dir_info["skip_count"] += 1
            if len(dir_info["done"]) < dir_info["total"]:
                return  # wait for remaining files in directory
            # All done — determine suffix
            if dir_info["failed_count"] > 0:
                suffix = self.file_problem_suffix.text().strip()
            elif dir_info.get("skip_count", 0) == dir_info["total"]:
                suffix = skip_suffix
            else:
                suffix = self.file_success_suffix.text().strip()
            if suffix:
                target = output_dir if has_container else output_path
                self._rename_to_suffix(target, suffix)
        else:
            if skip_suffix:
                self._rename_to_suffix(output_path, skip_suffix)

        if self.delete_source_combo.currentText() != "Keep":
            self._delete_source_folder(row)

    def _on_compression_done(self, row: int, success: bool, output_path: Path):
        QTimer.singleShot(0, lambda: self._do_compression_done(row, success, output_path))

    def _do_compression_done(self, row: int, success: bool, output_path: Path):
        try:
            task_id = self._row_task_ids[row] if row < len(self._row_task_ids) else None
            task = self._tasks_by_id.get(task_id) if task_id is not None else None
            is_remux = task.get("skip", False) if task else False

            success_suffix = (
                self.file_remux_suffix.text().strip() if is_remux
                else self.file_success_suffix.text().strip()
            )
            problem_suffix = self.file_problem_suffix.text().strip()

            delete_action = self.delete_source_combo.currentText()  # "Keep" / "Move to Bin" / "Delete Permanently"
            delete_source = delete_action != "Keep"

            source_file = task["source"] if task else None
            source_root = Path(self.source_edit.text().strip())

            # Determine if this file lives inside a named subdirectory (i.e. has a container)
            no_container = True
            dir_info = None
            if source_file:
                src_dir = source_file.parent
                no_container = src_dir.resolve() == source_root.resolve()
                dir_info = self._directory_results.get(src_dir)

            # Update per-directory tracking for files in a subdirectory
            if dir_info is not None:
                dir_info["done"].add(source_file)
                if success:
                    dir_info["success_count"] += 1
                else:
                    dir_info["failed_count"] += 1

            # For multi-file directories: defer rename/delete until all files in that dir
            # are processed. Single files (movies) and files directly in source root proceed
            # immediately.
            is_multi_file_dir = dir_info is not None and dir_info["total"] > 1
            if is_multi_file_dir:
                dir_all_done = len(dir_info["done"]) >= dir_info["total"]
                if not dir_all_done:
                    return  # wait for remaining files in this directory
                # Use success suffix only if every file in the dir succeeded
                effective_success = dir_info["failed_count"] == 0
            else:
                effective_success = success

            suffix = success_suffix if effective_success else problem_suffix
            if not suffix and not delete_source:
                return

            output_root = Path(self.output_edit.text().strip())
            output_dir = output_path.parent
            has_container = output_dir.resolve() != output_root.resolve()

            renamed_ok = True
            if suffix:
                if not effective_success and has_container:
                    # Encode failed — copy source into output dir so the user can inspect it,
                    # but only if the output dir has no video at all.
                    try:
                        video_files = [
                            f for f in output_dir.iterdir()
                            if f.suffix.lower() in {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts"}
                        ]
                    except OSError:
                        video_files = []
                    if not video_files and not is_multi_file_dir:
                        self._copy_source_to_output(row, output_dir)

                if has_container:
                    renamed_ok = self._rename_to_suffix(output_dir, suffix)
                else:
                    renamed_ok = self._rename_to_suffix(output_path, suffix)

            if delete_source and renamed_ok:
                self._delete_source_folder(row)
            elif delete_source and not renamed_ok:
                self._log(f"  ⚠ Skipping source delete — output rename did not succeed")
        except Exception as e:
            self._log(f"  ⚠ Error in post-processing: {e}")

    def _delete_source_folder(self, row: int):
        try:
            task_id = self._row_task_ids[row]
            task = self._tasks_by_id.get(task_id)
            if not task:
                return
            source_file = task.get("source")
            if not source_file or not source_file.exists():
                return
            use_bin = self.delete_source_combo.currentText() == "Move to Bin"
            source_root = Path(self.source_edit.text().strip())
            source_dir = source_file.parent
            no_container = source_dir.resolve() == source_root.resolve()
            target = source_file if no_container else source_dir
            if use_bin:
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "Finder" to delete POSIX file "{target}"'],
                    capture_output=True, timeout=10,
                )
                self._log(f"  Moved to Bin: {target.name}")
            elif no_container:
                source_file.unlink()
                self._log(f"  Deleted source file: {source_file.name}")
            else:
                source_file.unlink()
                shutil.rmtree(source_dir)
                self._log(f"  Deleted source: {source_dir}")
        except Exception as e:
            self._log(f"  ⚠ Could not delete source: {e}")

    def _copy_source_to_output(self, row: int, output_dir: Path):
        try:
            task_id = self._row_task_ids[row]
            task = self._tasks_by_id.get(task_id)
            if not task:
                return
            source_file = task.get("source")
            if not source_file:
                return
            output_dir.mkdir(parents=True, exist_ok=True)
            source_root = Path(self.source_edit.text().strip())
            source_dir = source_file.parent
            no_container = source_dir.resolve() == source_root.resolve()
            if no_container:
                files_to_copy = [source_file]
            else:
                try:
                    files_to_copy = [f for f in source_dir.iterdir() if f.is_file()]
                except OSError:
                    files_to_copy = [source_file]
            for f in files_to_copy:
                dest = output_dir / f.name
                if not dest.exists():
                    shutil.copy2(f, dest)
                    self._log(f"  Copied to output: {f.name}")
        except Exception as e:
            self._log(f"  ⚠ Could not copy source to output: {e}")

    def _rename_to_suffix(self, path: Path, suffix: str) -> bool:
        if not suffix:
            return True
        if path.is_file():
            new_name = f"{path.stem}.{suffix}{path.suffix}"
        else:
            new_name = f"{path.name}.{suffix}"
        new_path = path.parent / new_name
        if path == new_path:
            return True
        try:
            path.rename(new_path)
            self._log(f"  Renamed: {path.name} -> {new_name}")
            return True
        except OSError as e:
            self._log(f"  ⚠ Could not rename {path.name}: {e}")
            return False

    def _on_baseline_fps(self, fps: float):
        if self._baseline_fps == 0.0:
            self._baseline_fps = fps
            self._baseline_label.setText(f"{fps:.0f} Base FPS")
            min_fps = self.min_fps_spin.value()
            if fps > min_fps:
                self._baseline_label.setStyleSheet(
                    "color: #27ae60; font-weight: bold; font-size: 11px;"
                )
                self._log(f"Thermal baseline set: {fps:.0f} FPS\n")
            else:
                self._baseline_label.setStyleSheet(
                    "color: #c0392b; font-weight: bold; font-size: 11px;"
                )
                self._log(
                    f"⚠ Baseline {fps:.0f} FPS is below min FPS {min_fps} "
                    f"— files will continue but may be marked as problem files\n"
                )

    def _on_slow_file_abort(self, row: int):
        if not self._encode_worker:
            return
        t = self._encode_worker.task
        source_path = t["source"]
        retries = t.get("slow_file_retries", 0)
        t["slow_file_retries"] = retries + 1

        if retries >= 1:
            # Second attempt still below 200 FPS — mark as problem file
            if row < len(self._status_labels):
                self._completed_rows.add(row)
                self._set_status(row, "Problem file", "#e67e22")
                self._row_widgets[row].setStyleSheet(
                    "QWidget { background-color: rgba(230, 126, 34, 0.15); "
                    "border-left: 4px solid #e67e22; border-radius: 4px; }"
                )
                if row < len(self._delete_btns):
                    self._delete_btns[row].setEnabled(True)
            self._log(f"  ⚠ Still below {self.min_fps_spin.value()} FPS on retry — marking as problem file\n")
            self._problem_file_count += 1

            # Handle renaming for problem files from slow file abort
            self._on_compression_done(row, False, source_path)
            return

        # First attempt — short pause and retry
        self._cooling_down = True
        if row < len(self._status_labels):
            self._set_status(row, "Retrying in 10s…", "#d35400")
            self._progress_bars[row].setValue(0)
        self._log(f"  ⚠ Below {self.min_fps_spin.value()} FPS — retrying in 10 seconds\n")
        self._pending_tasks.insert(0, (t, row))
        QTimer.singleShot(10_000, self._resume_after_cooldown)

    def _resume_after_cooldown(self):
        self._cooling_down = False
        self._log("Cooldown complete — resuming encoding\n")
        self._start_next_encode()

    # ------------------------------------------------------------------
    # Stop / finish
    # ------------------------------------------------------------------

    def _on_stop(self):
        self._pending_tasks.clear()
        if self._encode_worker and self._encode_worker.isRunning():
            self._encode_worker.cancel_current()
        self.stop_btn.setEnabled(False)
        self._log("Stopping — current file cancelled.\n")

    def _on_encode_finished(self):
        self.stop_btn.hide()
        self.stop_btn.setEnabled(True)
        self._encoding_active = False
        self._stop_caffeinate()

        # Batch summary
        total = len(self._completed_rows)
        cool_mins = self._total_cooldown_secs / 60
        summary = (
            f"Batch complete: {total} file(s) processed\n"
            f"  Problem files:      {self._problem_file_count}\n"
            f"  Proactive cooldown: {cool_mins:.1f} minutes\n"
        )
        self._log(summary)

    def closeEvent(self, event):
        self._save_prefs()
        self._stop_caffeinate()
        if self._encode_worker and self._encode_worker.isRunning():
            self._encode_worker.cancel_current()
            if not self._encode_worker.wait(3000):
                self._encode_worker.terminate()
                self._encode_worker.wait(2000)
        event.accept()

    # ------------------------------------------------------------------
    # Preferences persistence
    # ------------------------------------------------------------------

    _PREFS_PATH = Path.home() / ".bulkvideocompressor.json"

    def _save_prefs(self):
        try:
            prefs = {
                "source_dir":       self.source_edit.text().strip(),
                "output_dir":       self.output_edit.text().strip(),
                "ffmpeg_path":      self.hb_path_edit.text().strip(),
                "preset":           self.preset_combo.currentText(),
                "preset_4k":        self.preset_4k_combo.currentText(),
                "audio_language":   self.audio_language_combo.currentText(),
                "subtitle_language": self.subtitle_language_combo.currentText(),
                "fallback_language": self.fallback_language_combo.currentText(),
                "prioritise_dts":   self.prioritise_dts_checkbox.isChecked(),
                "rf_quality":       self.rf_spin.value(),
                "rf_quality_4k":    self.rf_4k_spin.value(),
                "success_suffix":       self.file_success_suffix.text().strip(),
                "problem_suffix":       self.file_problem_suffix.text().strip(),
                "skip_suffix":          self.file_skip_suffix.text().strip(),
                "remux_suffix":         self.file_remux_suffix.text().strip(),
                "skip_threshold_4k":    self.skip_threshold_4k_spin.value(),
                "skip_threshold_1080p": self.skip_threshold_1080p_spin.value(),
                "delete_source":        self.delete_source_combo.currentText(),
                "min_fps":          self.min_fps_spin.value(),
                "cool_every":       self.cool_every_spin.value(),
                "cool_mins":        self.cool_mins_spin.value(),
            }
            self._PREFS_PATH.write_text(json.dumps(prefs, indent=2))
        except Exception:
            pass

    def _load_prefs(self):
        try:
            if not self._PREFS_PATH.exists():
                return
            prefs = json.loads(self._PREFS_PATH.read_text())
            if prefs.get("source_dir"):
                self.source_edit.setText(prefs["source_dir"])
            if prefs.get("output_dir"):
                self.output_edit.setText(prefs["output_dir"])
            if prefs.get("ffmpeg_path"):
                self.hb_path_edit.setText(prefs["ffmpeg_path"])
            if prefs.get("preset") in PRESETS:
                self.preset_combo.setCurrentText(prefs["preset"])
            if prefs.get("preset_4k") in PRESETS:
                self.preset_4k_combo.setCurrentText(prefs["preset_4k"])
            _valid_langs = Language.labels()
            if prefs.get("audio_language") in _valid_langs:
                self.audio_language_combo.setCurrentText(prefs["audio_language"])
            if prefs.get("subtitle_language") in _valid_langs:
                self.subtitle_language_combo.setCurrentText(prefs["subtitle_language"])
            if prefs.get("fallback_language") in _valid_langs:
                self.fallback_language_combo.setCurrentText(prefs["fallback_language"])
            if "prioritise_dts" in prefs:
                self.prioritise_dts_checkbox.setChecked(prefs["prioritise_dts"])
            if "rf_quality" in prefs:
                self.rf_spin.setValue(prefs["rf_quality"])
            if "rf_quality_4k" in prefs:
                self.rf_4k_spin.setValue(prefs["rf_quality_4k"])
            if "success_suffix" in prefs:
                self.file_success_suffix.setText(prefs["success_suffix"])
            if "problem_suffix" in prefs:
                self.file_problem_suffix.setText(prefs["problem_suffix"])
            if "skip_suffix" in prefs:
                self.file_skip_suffix.setText(prefs["skip_suffix"])
            if "remux_suffix" in prefs:
                self.file_remux_suffix.setText(prefs["remux_suffix"])
            if "skip_threshold_4k" in prefs:
                self.skip_threshold_4k_spin.setValue(prefs["skip_threshold_4k"])
            if "skip_threshold_1080p" in prefs:
                self.skip_threshold_1080p_spin.setValue(prefs["skip_threshold_1080p"])
            if prefs.get("delete_source") in ("Keep", "Move to Bin", "Delete Permanently"):
                self.delete_source_combo.setCurrentText(prefs["delete_source"])
            if "min_fps" in prefs:
                self.min_fps_spin.setValue(prefs["min_fps"])
            if "cool_every" in prefs:
                self.cool_every_spin.setValue(prefs["cool_every"])
            if "cool_mins" in prefs:
                self.cool_mins_spin.setValue(prefs["cool_mins"])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # macOS App Nap prevention
    # ------------------------------------------------------------------

    def _start_caffeinate(self):
        """Prevent macOS from throttling encoding via App Nap / idle sleep."""
        self._stop_caffeinate()
        try:
            self._caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-dims"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._log("caffeinate: preventing App Nap and sleep\n")
        except Exception:
            pass

    def _stop_caffeinate(self):
        if self._caffeinate_proc:
            try:
                self._caffeinate_proc.terminate()
                self._caffeinate_proc.wait(timeout=5)
            except Exception:
                pass
            self._caffeinate_proc = None

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log(self, text: str):
        self.log_edit.append(text)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )
