"""
Pre-encode review dialog — shows probed tasks for user confirmation.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class ReviewDialog(QDialog):
    def __init__(self, tasks: list, rf: float, preset_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review — confirm before encoding")
        self.setMinimumWidth(900)
        self.setMinimumHeight(380)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"<b>{len(tasks)} file(s)</b> · RF {rf} · {preset_name} · "
                "Audio Passthru · Subtitles <b>NOT</b> burned in"
            )
        )

        table = QTableWidget(len(tasks), 6)
        table.setHorizontalHeaderLabels(
            ["File", "Resolution", "FPS", "Audio", "Subtitles", "Burn-in"]
        )
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)

        for row, t in enumerate(tasks):
            info = t["info"]
            audio = t["audio"]
            subs = t["subs"]

            fps_str = f"{info.fps:.3f}".rstrip("0").rstrip(".")
            audio_str = (
                f"T{audio.index} · {audio.language or '?'} · Passthru"
                if audio
                else "None"
            )
            sub_parts = []
            for s in subs:
                kind = "Forced" if s.forced else ("SDH" if s.sdh else "Regular")
                sub_parts.append(f"T{s.index} {kind} [{s.language or '?'}]")

            def cell(text):
                item = QTableWidgetItem(str(text))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                return item

            enc_label = {
                "av1": "AV1",
                "x265_12bit": "H.265 12-bit",
                "x265": "H.265",
                "x264": "H.264",
                "hevc_videotoolbox": "H.265 HW",
                "h264_videotoolbox": "H.264 HW",
            }.get(t.get("encoder", "x265"), "H.265")
            table.setItem(row, 0, QTableWidgetItem(t["source"].name))
            table.setItem(row, 1, cell(f"{info.width}×{info.height} · {enc_label}"))
            table.setItem(row, 2, cell(fps_str))
            table.setItem(row, 3, cell(audio_str))
            table.setItem(row, 4, QTableWidgetItem(", ".join(sub_parts) or "None"))
            table.setItem(row, 5, cell("No ✓"))

        layout.addWidget(table)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Add to Queue")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
