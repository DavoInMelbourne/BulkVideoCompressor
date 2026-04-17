from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class QueueTabMixin:

    def _build_queue_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        btn_row = QHBoxLayout()
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedHeight(36)
        self.stop_btn.setStyleSheet(self._btn_style("#c0392b", "#e74c3c"))
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn)

        self.clear_btn = QPushButton("Clear completed")
        self.clear_btn.setFixedHeight(36)
        self.clear_btn.setStyleSheet(self._btn_style("#7f8c8d", "#95a5a6"))
        self.clear_btn.clicked.connect(self._on_clear_completed)
        self.clear_btn.setEnabled(False)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.progress_widget = QWidget()
        self.progress_layout = QVBoxLayout(self.progress_widget)
        self.progress_layout.setSpacing(4)
        self.progress_layout.setContentsMargins(4, 4, 4, 4)
        self.progress_layout.addStretch()

        self.progress_scroll = QScrollArea()
        self.progress_scroll.setWidget(self.progress_widget)
        self.progress_scroll.setWidgetResizable(True)
        self.progress_scroll.setMinimumHeight(160)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(80)
        self.log_edit.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: monospace; font-size: 12px; }"
        )

        self._bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        self._bottom_splitter.addWidget(self.progress_scroll)
        self._bottom_splitter.addWidget(self.log_edit)
        self._bottom_splitter.setStretchFactor(0, 3)
        self._bottom_splitter.setStretchFactor(1, 1)
        layout.addWidget(self._bottom_splitter)
        return page
