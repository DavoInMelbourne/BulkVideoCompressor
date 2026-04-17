from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QMessageBox


class HandlersMixin:

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

    def _handle_true_skip(self, row: int, source_file: Path, source_root: Path, output_path: Path):
        """File needs no remux — copy to output dir and apply skip suffix."""
        import shutil

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
