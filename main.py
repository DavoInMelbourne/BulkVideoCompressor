import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(45, 45, 45))
    p.setColor(QPalette.ColorRole.WindowText,       QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Base,             QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.AlternateBase,    QColor(45, 45, 45))
    p.setColor(QPalette.ColorRole.Text,             QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Button,           QColor(55, 55, 55))
    p.setColor(QPalette.ColorRole.ButtonText,       QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.BrightText,       QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Highlight,        QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.HighlightedText,  QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.ToolTipBase,      QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.ToolTipText,      QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Link,             QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.Mid,              QColor(80, 80, 80))
    p.setColor(QPalette.ColorRole.Dark,             QColor(20, 20, 20))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor(100, 100, 100))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(100, 100, 100))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(100, 100, 100))
    return p


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
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setApplicationName("Video Queue Manager")
    app.setWindowIcon(_make_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
