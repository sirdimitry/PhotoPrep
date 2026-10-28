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
