"""Immutable mask/crop plans in oriented image coordinates; originals stay read-only."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor


@dataclass(frozen=True)
class MaskStroke:
    points: tuple[tuple[float, float], ...]  # normalized to the oriented source image
    width: float  # diameter / min(source width, source height)
    erase: bool = False


@dataclass(frozen=True)
class CropRect:
    x: float
    y: float
    width: float
    height: float

    def pixels(self, width, height):
        return QRectF(self.x * width, self.y * height, self.width * width, self.height * height)


@dataclass(frozen=True)
class PhotoEdits:
    strokes: tuple[MaskStroke, ...] = ()
    crop: CropRect | None = None
    passes: tuple[tuple[MaskStroke, ...], ...] = ()  # successful passes; strokes is the next mask
    pass_models: tuple[str, ...] = ()

    @property
    def models_for_passes(self):
        return self.pass_models or ('lama',)*len(self.passes)


def fit_crop(width: int, height: int, ratio: float, existing: CropRect | None = None) -> CropRect:
    """Fit a fixed-ratio rectangle into the source, preserving an existing center."""
    if width <= 0 or height <= 0 or not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('Invalid crop geometry')
    if existing is None:
        cw = min(width, height * ratio)
        ch = cw / ratio
        cx, cy = width / 2, height / 2
    else:
        old = existing.pixels(width, height)
        cw = math.sqrt(old.width() * old.height() * ratio)
        ch = cw / ratio
        scale = min(1, width / cw, height / ch)
        cw, ch = cw * scale, ch * scale
        cx, cy = old.center().x(), old.center().y()
    x = min(width - cw, max(0, cx - cw / 2))
    y = min(height - ch, max(0, cy - ch / 2))
    return CropRect(x / width, y / height, cw / width, ch / height)


def paint_stroke(painter: QPainter, stroke: MaskStroke, width, height, *, overlay=False):
    if not stroke.points:
        return
    if overlay:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear if stroke.erase
                                   else QPainter.CompositionMode.CompositionMode_Source)
        color = QColor(250, 204, 21, 115)
    else:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        color = QColor('black' if stroke.erase else 'white')
    pen = QPen(color, stroke.width * min(width, height), Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    points = [QPointF(x * width, y * height) for x, y in stroke.points]
    if len(points) == 1:
        painter.drawPoint(points[0])
    else:
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        painter.drawPath(path)


def render_mask(width: int, height: int, strokes: tuple[MaskStroke, ...]) -> QImage:
    """Full-resolution grayscale mask for the later inference stage; no source edits."""
    if width <= 0 or height <= 0 or width * height > 100_000_000:
        raise ValueError('Mask dimensions exceed the safe limit')
    image = QImage(width, height, QImage.Format.Format_Grayscale8)
    if image.isNull():
        raise MemoryError('Could not allocate mask')
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        for stroke in strokes:
            paint_stroke(painter, stroke, width, height)
    finally:
        painter.end()
    return image
