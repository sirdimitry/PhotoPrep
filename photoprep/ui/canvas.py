"""Read-only canvas with high-DPI aware view operations."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QBrush, QColor, QImageReader, QPixmap, QPainter
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView


class PhotoCanvas(QGraphicsView):
    zoom_changed = Signal(int)
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._auto_fit = True
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#15171B")))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    @property
    def has_photo(self) -> bool:
        return self._pixmap_item is not None

    def clear_photo(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self.resetTransform()
        self.zoom_changed.emit(100)

    def load_photo(self, path: str) -> bool:
        reader = QImageReader(path)
        reader.setAutoTransform(True)  # EXIF orientation in-memory, source file untouched.
        img = reader.read()
        if img.isNull():
            return False
        self._scene.clear()
        pixmap = QPixmap.fromImage(img)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._auto_fit = True
        self.fit_photo()
        return True

    def fit_photo(self) -> None:
        if not self._pixmap_item:
            return
        self.resetTransform()
        bounds = self._pixmap_item.boundingRect().adjusted(-12, -12, 12, 12)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self._auto_fit = True
        self._emit_zoom()

    def actual_size(self) -> None:
        if not self._pixmap_item:
            return
        self.resetTransform()
        self.centerOn(self._pixmap_item)
        self._auto_fit = False
        self._emit_zoom()

    def zoom(self, factor: float) -> None:
        if not self._pixmap_item:
            return
        current = self.transform().m11()
        if not (0.05 <= current * factor <= 16):
            return
        self._auto_fit = False
        self.scale(factor, factor)
        self._emit_zoom()

    def wheelEvent(self, event) -> None:
        if not self._pixmap_item:
            event.ignore()
            return
        dy = event.angleDelta().y()
        if dy:
            self.zoom(1.12 ** (dy / 120.0))
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_photo()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(round(self.transform().m11() * 100))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
