from __future__ import annotations

import json
from pathlib import Path

from core.languages import Language
from ui.window.constants import PRESETS


class PrefsMixin:

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
                "rf_quality":           self.rf_spin.value(),
                "rf_quality_4k":        self.rf_4k_spin.value(),
                "rf_quality_4k_small":  self.rf_4k_small_spin.value(),
                "threshold_4k_small_gb": self.small_4k_threshold_spin.value(),
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
            if "rf_quality_4k_small" in prefs:
                self.rf_4k_small_spin.setValue(prefs["rf_quality_4k_small"])
            if "threshold_4k_small_gb" in prefs:
                self.small_4k_threshold_spin.setValue(prefs["threshold_4k_small_gb"])
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
