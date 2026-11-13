from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def make_icon(name: str, color: str = "#cad3f5", size: int = 16) -> QIcon:
    """Render a crisp vector QIcon at 1x and 2x DPI without external assets or emojis."""
    icon = QIcon()
    for scale in (1, 2):
        px = size * scale
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(scale, scale)
        pen = QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        _draw_glyph(painter, name, QColor(color))
        painter.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def _draw_glyph(p: QPainter, name: str, color: QColor) -> None:
    if name == "dashboard":
        p.drawRoundedRect(QRectF(2, 2, 5, 5), 1, 1)
        p.drawRoundedRect(QRectF(9, 2, 5, 5), 1, 1)
        p.drawRoundedRect(QRectF(2, 9, 5, 5), 1, 1)
        p.drawRoundedRect(QRectF(9, 9, 5, 5), 1, 1)
    elif name == "repos":
        path = QPainterPath()
        path.moveTo(2, 4)
        path.lineTo(6.5, 4)
        path.lineTo(8, 5.5)
        path.lineTo(14, 5.5)
        path.lineTo(14, 13)
        path.lineTo(2, 13)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "tasks":
        path = QPainterPath()
        path.moveTo(9.5, 1.5)
        path.lineTo(4, 8.5)
        path.lineTo(8.5, 8.5)
        path.lineTo(6.5, 14.5)
        path.lineTo(12, 7.5)
        path.lineTo(7.5, 7.5)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "cache":
        p.drawEllipse(QRectF(3, 2.2, 10, 3.2))
        p.drawLine(QPointF(3, 3.8), QPointF(3, 12.2))
        p.drawLine(QPointF(13, 3.8), QPointF(13, 12.2))
        p.drawArc(QRectF(3, 10.6, 10, 3.2), 180 * 16, 180 * 16)
        p.drawArc(QRectF(3, 6.4, 10, 3.2), 180 * 16, 180 * 16)
    elif name == "ledger":
        p.drawRoundedRect(QRectF(3, 2, 10, 12), 1.5, 1.5)
        p.drawLine(QPointF(5.5, 5.5), QPointF(10.5, 5.5))
        p.drawLine(QPointF(5.5, 8.5), QPointF(10.5, 8.5))
        p.drawLine(QPointF(5.5, 11.2), QPointF(8.5, 11.2))
    elif name == "agents":
        path = QPainterPath()
        path.moveTo(8, 2)
        path.lineTo(13, 4)
        path.lineTo(13, 8.5)
        path.quadTo(13, 12.2, 8, 14)
        path.quadTo(3, 12.2, 3, 8.5)
        path.lineTo(3, 4)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "settings":
        p.drawEllipse(QRectF(5.5, 5.5, 5, 5))
        p.drawEllipse(QRectF(2.5, 2.5, 11, 11))
    elif name == "add":
        p.drawLine(QPointF(8, 3), QPointF(8, 13))
        p.drawLine(QPointF(3, 8), QPointF(13, 8))
    elif name == "refresh":
        p.drawArc(QRectF(3, 3, 10, 10), 35 * 16, 285 * 16)
        p.drawLine(QPointF(12.2, 3.2), QPointF(13.2, 6.2))
        p.drawLine(QPointF(12.2, 3.2), QPointF(9.5, 4.0))
    elif name == "play":
        path = QPainterPath()
        path.moveTo(4.5, 3)
        path.lineTo(12.5, 8)
        path.lineTo(4.5, 13)
        path.closeSubpath()
        p.setBrush(color)
        p.drawPath(path)
    elif name == "stop":
        p.setBrush(color)
        p.drawRoundedRect(QRectF(4, 4, 8, 8), 1, 1)
    elif name == "trash":
        p.drawLine(QPointF(3, 4.5), QPointF(13, 4.5))
        p.drawLine(QPointF(6, 2.5), QPointF(10, 2.5))
        p.drawRoundedRect(QRectF(4.2, 4.5, 7.6, 9.2), 1, 1)
    elif name == "broom":
        p.drawLine(QPointF(12.5, 2.5), QPointF(6.5, 9))
        path = QPainterPath()
        path.moveTo(5.5, 8.2)
        path.lineTo(8.5, 10.2)
        path.lineTo(5.2, 13.8)
        path.lineTo(2.4, 11.8)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "copy":
        p.drawRoundedRect(QRectF(5.5, 5, 8, 9), 1, 1)
        p.drawLine(QPointF(3, 10.5), QPointF(3, 2.5))
        p.drawLine(QPointF(3, 2.5), QPointF(10.5, 2.5))
    elif name == "check":
        p.drawLine(QPointF(3.2, 8.2), QPointF(6.5, 11.5))
        p.drawLine(QPointF(6.5, 11.5), QPointF(13, 4.5))
    elif name == "pause":
        p.drawLine(QPointF(5.5, 3.5), QPointF(5.5, 12.5))
        p.drawLine(QPointF(10.5, 3.5), QPointF(10.5, 12.5))
    elif name == "unlock":
        p.drawRoundedRect(QRectF(3.5, 7, 9, 6.5), 1.2, 1.2)
        p.drawArc(QRectF(5, 2.5, 6, 6), 0, 145 * 16)
    elif name == "search":
        p.drawEllipse(QRectF(2.5, 2.5, 8, 8))
        p.drawLine(QPointF(9.5, 9.5), QPointF(13.5, 13.5))
    elif name == "export":
        p.drawLine(QPointF(8, 2.5), QPointF(8, 10))
        p.drawLine(QPointF(5, 5.5), QPointF(8, 2.5))
        p.drawLine(QPointF(11, 5.5), QPointF(8, 2.5))
        p.drawLine(QPointF(3, 11), QPointF(3, 13.5))
        p.drawLine(QPointF(3, 13.5), QPointF(13, 13.5))
        p.drawLine(QPointF(13, 13.5), QPointF(13, 11))
