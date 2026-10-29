"""Resource lookup from checkout and editable installation."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def icon_path(name: str) -> str:
    return str(ROOT / "assets" / "icons" / (name + ".png"))


def app_icon_path() -> str:
    return str(ROOT / "assets" / "app-icon.png")


def ui_icon(name, appearance='dark', primary=False):
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    pixmap = QPixmap(icon_path(name))
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(),QColor('#1A1C20' if primary else '#465160' if appearance == 'light' else '#C4CAD3'))
    painter.end()
    return QIcon(pixmap)


def reset_icon(appearance='dark'):
    """Theme-aware vector reset arrow, rendered sharply on Retina screens."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
    pixmap = QPixmap(48,48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2,2)
    pen = QPen(QColor('#465160' if appearance=='light' else '#C4CAD3'),1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    path = QPainterPath()
    path.moveTo(3,10)
    path.cubicTo(4,5,7,3,12,3)
    path.cubicTo(17,3,21,7,21,12)
    path.cubicTo(21,17,17,21,12,21)
    path.cubicTo(8,21,5,19,3.5,16)
    path.moveTo(3,4);path.lineTo(3,10);path.lineTo(9,10)
    painter.drawPath(path)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
