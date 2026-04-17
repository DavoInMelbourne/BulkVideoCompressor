from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.handbrake import kill_orphan_ffmpeg, find_ffmpeg
from ui.window.constants import PRESETS, DEFAULT_PRESET, DEFAULT_PRESET_4K, DEFAULT_RF_4K, DEFAULT_RF_4K_SMALL, DEFAULT_4K_SMALL_THRESHOLD_GB
from ui.window.settings_tab import SettingsTabMixin
from ui.window.queue_tab import QueueTabMixin


class BuildUIMixin(SettingsTabMixin, QueueTabMixin):

    def _build_ui(self):
        about_action = QAction("About BVC", self)
        about_action.triggered.connect(self._show_about)
        self.menuBar().addMenu("BulkVideoCompressor").addAction(about_action)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tab_widget = QTabWidget()
        self._tab_widget.addTab(self._build_settings_tab(), "Settings")
        self._tab_widget.addTab(self._build_queue_tab(), "Queue")
        root.addWidget(self._tab_widget)

    # ------------------------------------------------------------------
    # Shared UI helpers (used by both tabs and progress rows)
    # ------------------------------------------------------------------

    def _btn_style(self, normal, hover):
        return (
            f"QPushButton {{ background-color: {normal}; color: white; font-size: 13px; "
            "border-radius: 4px; } "
            f"QPushButton:hover {{ background-color: {hover}; }} "
            "QPushButton:disabled { background-color: #7f8c8d; }"
        )

    def _dir_group(self, title, attr_name, browse_fn, default="") -> QGroupBox:
        from ui.window.settings_tab import _inp, _INPUT_HEIGHT, _group_row
        g, row = _group_row(title)
        edit = _inp(QLineEdit())
        if default:
            edit.setText(default)
        else:
            edit.setPlaceholderText(f"Select {title.lower()}…")
        setattr(self, attr_name, edit)
        row.addWidget(edit)
        btn = QPushButton("Browse")
        btn.setFixedHeight(_INPUT_HEIGHT)
        btn.setFixedWidth(80)
        btn.clicked.connect(browse_fn)
        row.addWidget(btn)
        return g

    @staticmethod
    def _rf_hint_text(preset_name: str) -> str:
        encoder, _, _ = PRESETS[preset_name]
        if "videotoolbox" in encoder:
            return "↑ higher = better quality"
        return "↓ lower = better quality"

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
        self.rf_4k_small_spin.setValue(DEFAULT_RF_4K_SMALL)
        self.small_4k_threshold_spin.setValue(int(DEFAULT_4K_SMALL_THRESHOLD_GB))
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
        orphans = kill_orphan_ffmpeg()
        if orphans:
            self._log(f"Killed {orphans} orphan ffmpeg process(es) from a previous run.")
        cli = find_ffmpeg()
        if cli:
            self.hb_path_edit.setText(str(cli))
            self._log(f"Found ffmpeg: {cli}")
        else:
            self._log("ffmpeg not found — please set path manually.")

    def _browse_source(self):
        d = QFileDialog.getExistingDirectory(self, "Select Source Directory")
        if d:
            self.source_edit.setText(d)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_edit.setText(d)

    def _browse_cli(self):
        p, _ = QFileDialog.getOpenFileName(self, "Locate ffmpeg")
        if p:
            self.hb_path_edit.setText(p)

    def _add_progress_row(self, filename: str, task_id: int):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QProgressBar

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

        self.progress_layout.insertWidget(self.progress_layout.count() - 1, row_widget)
        self._progress_bars.append(bar)
        self._progress_labels.append(eta_lbl)
        self._status_labels.append(status_lbl)
        self._delete_btns.append(del_btn)
        self._row_task_ids.append(task_id)
        self._row_widgets.append(row_widget)
        self.progress_scroll.verticalScrollBar().setValue(
            self.progress_scroll.verticalScrollBar().maximum()
        )
