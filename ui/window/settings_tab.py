from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.languages import Language
from ui.window.constants import (
    PRESETS,
    DEFAULT_PRESET,
    DEFAULT_PRESET_4K,
    DEFAULT_RF_4K,
    DEFAULT_RF_4K_SMALL,
    DEFAULT_4K_SMALL_THRESHOLD_GB,
)

_INPUT_HEIGHT = 36
_INPUT_FONT_SIZE = 13
_ROW_HEIGHT = _INPUT_HEIGHT + 8   # 44px — container gives controls room to breathe
_S = 12                            # spacing between controls


def _inp(widget, width: int | None = None):
    """Fix height and font on any input widget."""
    widget.setFixedHeight(_INPUT_HEIGHT)
    f = widget.font()
    f.setPointSize(_INPUT_FONT_SIZE)
    widget.setFont(f)
    if width is not None:
        widget.setFixedWidth(width)
    return widget


def _lbl(text: str) -> QLabel:
    """Label with fixed height so it never drives the row taller than _INPUT_HEIGHT."""
    lbl = QLabel(text)
    lbl.setFixedHeight(_INPUT_HEIGHT)
    lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    return lbl


def _group_row(title: str) -> tuple[QGroupBox, QHBoxLayout]:
    """
    Return (group_box, row_layout).

    Use direct layout on the group box with minimum height.
    """
    from PyQt6.QtWidgets import QSizePolicy
    grp = QGroupBox(title)
    grp.setMinimumHeight(66)
    grp.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row = QHBoxLayout(grp)
    row.setContentsMargins(14, 12, 14, 12)
    row.setSpacing(_S)
    return grp, row


class SettingsTabMixin:

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        # Fusion style (set globally) renders controls within their geometry correctly.
        # No explicit stylesheet needed — Fusion picks up the system palette automatically.
        layout = QVBoxLayout(page)
        layout.setSpacing(18)
        layout.setContentsMargins(16, 16, 16, 16)

        layout.addWidget(self._dir_group("Source Directory", "source_edit", self._browse_source))
        layout.addSpacing(12)
        layout.addWidget(self._dir_group("Output Directory", "output_edit", self._browse_output))
        layout.addSpacing(12)
        layout.addWidget(self._build_1080p_group())
        layout.addSpacing(12)
        layout.addWidget(self._build_4k_group())
        layout.addSpacing(12)
        layout.addWidget(self._build_skip_group())
        layout.addSpacing(12)
        layout.addWidget(self._build_language_group())
        layout.addSpacing(12)
        layout.addWidget(self._build_post_group())
        layout.addSpacing(12)
        layout.addWidget(self._build_thermal_group())
        layout.addSpacing(12)
        layout.addWidget(self._build_ffmpeg_group())
        layout.addSpacing(6)

        self.scan_btn = QPushButton("Scan && Review")
        self.scan_btn.setFixedHeight(42)
        self.scan_btn.setStyleSheet(self._btn_style("#2980b9", "#3498db"))
        self.scan_btn.clicked.connect(self._on_scan)
        layout.addWidget(self.scan_btn)

        layout.addStretch()
        return page

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_1080p_group(self) -> QGroupBox:
        grp, row = _group_row("Encoding Options — 1080p & below")

        row.addWidget(_lbl("Preset:"))
        self.preset_combo = _inp(QComboBox())
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.setCurrentText(DEFAULT_PRESET)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        row.addWidget(self.preset_combo)

        row.addSpacing(16)
        row.addWidget(_lbl("RF:"))
        self.rf_spin = _inp(QDoubleSpinBox(), 80)
        self.rf_spin.setRange(0, 100)
        self.rf_spin.setValue(PRESETS[DEFAULT_PRESET][2])
        self.rf_spin.setSingleStep(0.5)
        self.rf_spin.setDecimals(1)
        self.rf_spin.setToolTip(
            "Software (x264/x265/AV1): lower = better quality\n"
            "Hardware (VideoToolbox): higher = better quality"
        )
        row.addWidget(self.rf_spin)

        self.rf_hint_label = _lbl("")
        self.rf_hint_label.setStyleSheet("color: #888; font-size: 11px;")
        row.addWidget(self.rf_hint_label)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setFixedHeight(_INPUT_HEIGHT)
        reset_btn.clicked.connect(self._on_reset_defaults)
        row.addWidget(reset_btn)
        
        row.addStretch()

        self._update_rf_hint(DEFAULT_PRESET, self.rf_hint_label)
        return grp

    def _build_4k_group(self) -> QGroupBox:
        grp, row = _group_row("4K Encoding Options")

        row.addWidget(_lbl("Small 4K — under"))

        self.small_4k_threshold_spin = _inp(QSpinBox(), 90)
        self.small_4k_threshold_spin.setRange(1, 200)
        self.small_4k_threshold_spin.setValue(int(DEFAULT_4K_SMALL_THRESHOLD_GB))
        self.small_4k_threshold_spin.setSingleStep(1)
        self.small_4k_threshold_spin.setSuffix(" GB")
        self.small_4k_threshold_spin.setToolTip(
            "4K files under this size use the Small 4K RF.\n"
            "Files at or above use the Large 4K preset."
        )
        row.addWidget(self.small_4k_threshold_spin)

        row.addSpacing(6)
        row.addWidget(_lbl("RF:"))
        self.rf_4k_small_spin = _inp(QDoubleSpinBox(), 80)
        self.rf_4k_small_spin.setRange(0, 100)
        self.rf_4k_small_spin.setValue(DEFAULT_RF_4K_SMALL)
        self.rf_4k_small_spin.setSingleStep(0.5)
        self.rf_4k_small_spin.setDecimals(1)
        self.rf_4k_small_spin.setToolTip(
            "VideoToolbox quality for small 4K files.\nHigher = better quality / less compression."
        )
        row.addWidget(self.rf_4k_small_spin)

        row.addSpacing(32)
        row.addWidget(_lbl("Large 4K — preset:"))
        self.preset_4k_combo = _inp(QComboBox())
        self.preset_4k_combo.addItems(list(PRESETS.keys()))
        self.preset_4k_combo.setCurrentText(DEFAULT_PRESET_4K)
        self.preset_4k_combo.currentTextChanged.connect(self._on_4k_preset_changed)
        row.addWidget(self.preset_4k_combo)

        row.addSpacing(16)
        row.addWidget(_lbl("RF:"))
        self.rf_4k_spin = _inp(QDoubleSpinBox(), 80)
        self.rf_4k_spin.setRange(0, 100)
        self.rf_4k_spin.setValue(DEFAULT_RF_4K)
        self.rf_4k_spin.setSingleStep(0.5)
        self.rf_4k_spin.setDecimals(1)
        self.rf_4k_spin.setToolTip(
            "VideoToolbox quality for large 4K files.\nHigher = better quality / less compression."
        )
        row.addWidget(self.rf_4k_spin)

        self.rf_4k_hint_label = _lbl("")
        self.rf_4k_hint_label.setStyleSheet("color: #888; font-size: 11px;")
        row.addWidget(self.rf_4k_hint_label)

        row.addStretch()
        self._update_rf_hint(DEFAULT_PRESET_4K, self.rf_4k_hint_label)
        return grp

    def _build_skip_group(self) -> QGroupBox:
        grp, row = _group_row("Smart Skip — already compressed (hevc / av1)")

        row.addWidget(_lbl("Skip 4K if under:"))
        self.skip_threshold_4k_spin = _inp(QDoubleSpinBox(), 100)
        self.skip_threshold_4k_spin.setRange(0, 200)
        self.skip_threshold_4k_spin.setValue(20.0)
        self.skip_threshold_4k_spin.setSingleStep(1.0)
        self.skip_threshold_4k_spin.setDecimals(1)
        self.skip_threshold_4k_spin.setSuffix(" GB")
        self.skip_threshold_4k_spin.setToolTip(
            "4K hevc/av1 files smaller than this are skipped (already well compressed)."
        )
        row.addWidget(self.skip_threshold_4k_spin)

        row.addSpacing(32)
        row.addWidget(_lbl("Skip 1080p & below if under:"))
        self.skip_threshold_1080p_spin = _inp(QDoubleSpinBox(), 100)
        self.skip_threshold_1080p_spin.setRange(0, 200)
        self.skip_threshold_1080p_spin.setValue(4.0)
        self.skip_threshold_1080p_spin.setSingleStep(0.5)
        self.skip_threshold_1080p_spin.setDecimals(1)
        self.skip_threshold_1080p_spin.setSuffix(" GB")
        self.skip_threshold_1080p_spin.setToolTip(
            "1080p and below hevc/av1 files smaller than this are skipped."
        )
        row.addWidget(self.skip_threshold_1080p_spin)
        row.addStretch()
        return grp

    def _build_language_group(self) -> QGroupBox:
        grp, row = _group_row("Language Preferences")
        _lang_labels = Language.labels()

        row.addWidget(_lbl("Audio:"))
        self.audio_language_combo = _inp(QComboBox())
        self.audio_language_combo.addItems(_lang_labels)
        self.audio_language_combo.setCurrentText("Original Language")
        self.audio_language_combo.setToolTip(
            "Preferred audio track language.\n"
            "For non-English selections the first non-English track in that language is chosen."
        )
        row.addWidget(self.audio_language_combo)

        row.addSpacing(24)
        row.addWidget(_lbl("Subtitles:"))
        self.subtitle_language_combo = _inp(QComboBox())
        self.subtitle_language_combo.addItems(_lang_labels)
        self.subtitle_language_combo.setCurrentText("English")
        self.subtitle_language_combo.setToolTip("Preferred subtitle language.")
        row.addWidget(self.subtitle_language_combo)

        row.addSpacing(24)
        row.addWidget(_lbl("Fallback:"))
        self.fallback_language_combo = _inp(QComboBox())
        self.fallback_language_combo.addItems(_lang_labels)
        self.fallback_language_combo.setCurrentText("English")
        self.fallback_language_combo.setToolTip(
            "Used for both audio and subtitles when the preferred language is not found."
        )
        row.addWidget(self.fallback_language_combo)

        row.addSpacing(24)
        self.prioritise_dts_checkbox = QCheckBox("Prioritise DTS")
        self.prioritise_dts_checkbox.setChecked(True)
        self.prioritise_dts_checkbox.setToolTip("Prefer DTS/TrueHD audio tracks over other codecs")
        row.addWidget(self.prioritise_dts_checkbox)
        row.addStretch()
        return grp

    def _build_post_group(self) -> QGroupBox:
        grp, row = _group_row("Post Processing")

        for attr, label, default, tip in [
            ("file_success_suffix", "Success:",  "Done",  "Suffix added on successful compress."),
            ("file_problem_suffix", "Problem:",  "Check", "Suffix added on failed compress."),
            ("file_skip_suffix",    "Skip:",     "Skip",  "Suffix added when skipped."),
            ("file_remux_suffix",   "Remux:",    "Remux", "Suffix added after a remux."),
        ]:
            row.addWidget(_lbl(label))
            edit = _inp(QLineEdit(), 80)
            edit.setText(default)
            edit.setToolTip(tip)
            setattr(self, attr, edit)
            row.addWidget(edit)
            row.addSpacing(8)

        row.addSpacing(8)
        row.addWidget(_lbl("After success:"))
        self.delete_source_combo = _inp(QComboBox())
        self.delete_source_combo.addItems(["Keep", "Move to Bin", "Delete Permanently"])
        self.delete_source_combo.setCurrentText("Keep")
        self.delete_source_combo.setToolTip(
            "What to do with the source after a verified successful encode.\n"
            "Move to Bin is recommended."
        )
        row.addWidget(self.delete_source_combo)
        row.addStretch()
        return grp

    def _build_thermal_group(self) -> QGroupBox:
        grp, row = _group_row("Thermal Safeguards")

        row.addWidget(_lbl("Min FPS:"))
        self.min_fps_spin = _inp(QSpinBox(), 80)
        self.min_fps_spin.setRange(10, 1000)
        self.min_fps_spin.setValue(80)
        self.min_fps_spin.setToolTip(
            "Minimum expected FPS at 10% progress.\nFiles below this are flagged as problem files."
        )
        row.addWidget(self.min_fps_spin)

        self._baseline_label = _lbl("")
        self._baseline_label.setStyleSheet("color: #27ae60; font-weight: bold; font-size: 11px;")
        row.addWidget(self._baseline_label)

        row.addSpacing(32)
        row.addWidget(_lbl("Cool every:"))
        self.cool_every_spin = _inp(QSpinBox(), 100)
        self.cool_every_spin.setRange(1, 200)
        self.cool_every_spin.setValue(10)
        self.cool_every_spin.setSuffix(" files")
        self.cool_every_spin.setToolTip("Insert a proactive cooldown after this many files")
        row.addWidget(self.cool_every_spin)

        row.addSpacing(8)
        row.addWidget(_lbl("for"))
        self.cool_mins_spin = _inp(QDoubleSpinBox(), 90)
        self.cool_mins_spin.setRange(0.5, 30.0)
        self.cool_mins_spin.setValue(2.0)
        self.cool_mins_spin.setSingleStep(0.5)
        self.cool_mins_spin.setDecimals(1)
        self.cool_mins_spin.setSuffix(" min")
        self.cool_mins_spin.setToolTip("Duration of proactive cooldown")
        row.addWidget(self.cool_mins_spin)
        row.addStretch()
        return grp

    def _build_ffmpeg_group(self) -> QGroupBox:
        grp, row = _group_row("ffmpeg")
        row.addWidget(_lbl("Path:"))
        self.hb_path_edit = _inp(QLineEdit())
        self.hb_path_edit.setPlaceholderText("Auto-detected — override if needed")
        row.addWidget(self.hb_path_edit)
        b = QPushButton("Browse")
        b.setFixedHeight(_INPUT_HEIGHT)
        b.setFixedWidth(80)
        b.clicked.connect(self._browse_cli)
        row.addWidget(b)
        return grp
