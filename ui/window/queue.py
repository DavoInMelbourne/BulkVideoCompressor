from __future__ import annotations

import subprocess
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QDialog, QMessageBox

from core.handbrake import find_ffmpeg, find_ffprobe
from core.languages import Language
from ui.workers import EncodeWorker, ProbeWorker
from ui.window.constants import PRESETS


class QueueMixin:

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
        from ui.review_dialog import ReviewDialog

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
        threshold_4k_bytes    = self.skip_threshold_4k_spin.value()    * 1_000_000_000
        threshold_1080p_bytes = self.skip_threshold_1080p_spin.value() * 1_000_000_000
        small_4k_threshold_bytes = self.small_4k_threshold_spin.value() * 1_000_000_000
        rf_4k_small = self.rf_4k_small_spin.value()
        for t in tasks:
            info = t["info"]
            is_4k = info.height >= 2160 or info.width >= 3840
            if is_4k:
                t["encoder"] = encoder_4k
                t["encoder_preset"] = encoder_preset_4k
                t["rf"] = rf_4k_small if info.file_size_bytes < small_4k_threshold_bytes else rf_4k
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

        msg = f"→ {added} file(s) added to queue."
        if duplicates:
            msg += f" ({duplicates} duplicate(s) skipped)"
        self._log(msg + "\n")

        if not self._encoding_active:
            self._encoding_active = True
            self._start_caffeinate()
            self.stop_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
            self._tab_widget.setCurrentIndex(1)
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

    def _resume_after_cooldown(self):
        self._cooling_down = False
        self._log("Cooldown complete — resuming encoding\n")
        self._start_next_encode()

    def _on_stop(self):
        self._pending_tasks.clear()
        if self._encode_worker and self._encode_worker.isRunning():
            self._encode_worker.cancel_current()
        self.stop_btn.setEnabled(False)
        self._log("Stopping — current file cancelled.\n")

    def _on_encode_finished(self):
        self.stop_btn.setEnabled(False)
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
