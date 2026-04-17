from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import QTimer


class PostProcessMixin:

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
            if not effective_success:
                # Always ensure source files are in the output folder on failure
                # so the target is complete and the source can be safely deleted.
                self._copy_source_to_output(row, output_dir)
            if suffix:

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
        """Copy all source files to output_dir on failure.

        The original video always overwrites any partial encode.
        Extras (NFO, subtitles, artwork) are copied only if not already present.
        """
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

            # Collect files to copy: for a contained movie, grab everything in
            # the source folder; for a bare file in the source root, just the video.
            if no_container:
                files_to_copy = [source_file]
            else:
                try:
                    files_to_copy = [f for f in source_dir.iterdir() if f.is_file()]
                except OSError:
                    files_to_copy = [source_file]

            video_exts = {".mkv", ".mp4", ".avi", ".mov", ".ts", ".m2ts"}
            for f in files_to_copy:
                dest = output_dir / f.name
                is_video = f.suffix.lower() in video_exts
                if is_video or not dest.exists():
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
