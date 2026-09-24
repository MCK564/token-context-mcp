from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LoadingSpinner(QWidget):
    """Modern lightweight animated spinner widget using pure QPainter."""

    def __init__(self, parent: QWidget | None = None, size: int = 36) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.start(40)  # ~25 FPS

    def _rotate(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        radius = min(width, height) / 2 - 4

        painter.translate(width / 2, height / 2)
        painter.rotate(self._angle)

        pen = QPen()
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # Draw 12 fading segments
        for i in range(12):
            alpha = int(255 * (i / 12))
            pen.setColor(QColor(137, 180, 250, alpha))
            painter.setPen(pen)
            painter.drawLine(0, int(radius * 0.6), 0, int(radius))
            painter.rotate(30)


class LoadingOverlay(QWidget):
    """
    Semi-transparent floating overlay displaying an animated spinner
    and status text while background tasks or data loading are underway.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        self.spinner = LoadingSpinner(self, size=40)
        layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        self.text_label = QLabel("Loading...", self)
        self.text_label.setStyleSheet("color: #cad3f5; font-size: 13px; font-weight: 600;")
        layout.addWidget(self.text_label, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_loading(self, message: str = "Loading...") -> None:
        self.text_label.setText(message)
        if self.parentWidget():
            self.resize(self.parentWidget().size())
            self.raise_()
        self.show()

    def hide_loading(self) -> None:
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        # Semi-transparent dark background
        painter.fillRect(self.rect(), QColor(24, 24, 37, 190))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
