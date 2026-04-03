import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _make_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Blue rounded background
    p.setBrush(QColor("#2980b9"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    # White "HB" text
    font = QFont("Arial", 18, QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "BVC")
    p.end()
    return QIcon(pix)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Video Queue Manager")
    app.setWindowIcon(_make_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
