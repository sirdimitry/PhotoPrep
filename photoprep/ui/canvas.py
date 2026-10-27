"""Asynchronous, bounded-cache photo preview with per-photo view state."""
from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QObject, QRunnable, QThreadPool
from PySide6.QtGui import QBrush, QColor, QImage, QImageReader, QPixmap, QPainter
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from ..workspace import ViewState


class DecodeSignals(QObject):
    result = Signal(int, str, object, str)


class DecodePhoto(QRunnable):
    def __init__(self, token: int, path: str):
        super().__init__()
        self.setAutoDelete(False)
        self.token, self.path = token, path
        self.signals = DecodeSignals()

    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        try:
            image = reader.read()
            self.signals.result.emit(self.token, self.path, image, reader.errorString() if image.isNull() else '')
        except Exception as exc:
            self.signals.result.emit(self.token, self.path, QImage(), str(exc))


class PhotoCanvas(QGraphicsView):
    zoom_changed = Signal(int)
    files_dropped = Signal(list)
    photo_loaded = Signal(str, bool)
    loading_changed = Signal(bool)
    view_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._auto_fit = True
        self.current_path: str | None = None
        self.loading = False
        self._restoring = False
        self.view_dirty = False
        self._token = 0
        self._pending_view = ViewState()
        self._workers = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self.cache_limit = 128 * 1024 * 1024
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(QColor('#15171B')))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.horizontalScrollBar().valueChanged.connect(self._scroll_changed)
        self.verticalScrollBar().valueChanged.connect(self._scroll_changed)

    @property
    def has_photo(self) -> bool:
        return self._pixmap_item is not None

    def _clear_image(self):
        self._pixmap_item = None
        self.current_path = None
        self.view_dirty = False
        self._scene.clear()
        self._scene.setSceneRect(QRectF())
        self.resetTransform()

    def clear_photo(self):
        self._token += 1  # Ignore work still finishing in the background.
        self._cancel_pending()
        self._clear_image()
        self.loading = False
        self.loading_changed.emit(False)
        self.zoom_changed.emit(100)

    def _cancel_pending(self):
        for token, worker in list(self._workers.items()):
            if self._pool.tryTake(worker):
                self._workers.pop(token, None)

    @staticmethod
    def _signature(path):
        try:
            stat = Path(path).stat()
            return path, stat.st_mtime_ns, stat.st_size
        except OSError:
            return path, None, None

    def load_photo(self, path: str, state: ViewState | None = None):
        self._token += 1
        self._cancel_pending()
        self._pending_view = state or ViewState()
        self._clear_image()
        self.loading = True
        self.loading_changed.emit(True)
        key = self._signature(path)
        if key[1] is None:
            self.loading = False
            self.loading_changed.emit(False)
            self.photo_loaded.emit(path, False)
            return
        if key in self._cache:
            image = self._cache.pop(key)
            self._cache[key] = image
            self._apply_image(path, image)
            return
        worker = DecodePhoto(self._token, path)
        self._workers[self._token] = worker
        worker.signals.result.connect(self._decoded, Qt.ConnectionType.QueuedConnection)
        self._pool.start(worker)

    def _decoded(self, token, path, image, error):
        self._workers.pop(token, None)
        # Late results cannot replace a more recently selected photo.
        if token != self._token:
            return
        if image.isNull():
            self.loading = False
            self.loading_changed.emit(False)
            self.photo_loaded.emit(path, False)
            return
        size = image.sizeInBytes()
        if size <= self.cache_limit:
            # Drop stale versions of the same file before adding its new image.
            for key in list(self._cache):
                if key[0] == path:
                    self._cache_bytes -= self._cache.pop(key).sizeInBytes()
            while self._cache and self._cache_bytes + size > self.cache_limit:
                _, old = self._cache.popitem(last=False)
                self._cache_bytes -= old.sizeInBytes()
            self._cache[self._signature(path)] = image
            self._cache_bytes += size
        self._apply_image(path, image)

    def _apply_image(self, path, image):
        pixmap = QPixmap.fromImage(image)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._pixmap_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.current_path = path
        self.loading = False
        self.restore_view(self._pending_view)
        self.view_dirty = False
        self.loading_changed.emit(False)
        self.photo_loaded.emit(path, True)

    def view_state(self) -> ViewState:
        if not self._pixmap_item or self._auto_fit:
            return ViewState()
        center = self.mapToScene(self.viewport().rect().center())
        bounds = self._pixmap_item.boundingRect()
        return ViewState(self._auto_fit, self.transform().m11() * self.devicePixelRatioF(),
                         min(1, max(0, center.x() / bounds.width())),
                         min(1, max(0, center.y() / bounds.height())))

    def restore_view(self, state: ViewState, *, user_action=False):
        if not self._pixmap_item:
            return
        if state.fit:
            self.fit_photo(user_action=user_action)
            return
        self._restoring = True
        try:
            self.resetTransform()
            self.scale(state.zoom / self.devicePixelRatioF(), state.zoom / self.devicePixelRatioF())
            bounds = self._pixmap_item.boundingRect()
            self.centerOn(bounds.width() * state.center_x, bounds.height() * state.center_y)
            self._auto_fit = False
            self._emit_zoom()
        finally:
            self._restoring = False
        if user_action:
            self._notify_view()

    def fit_photo(self, *, user_action=True):
        if not self._pixmap_item:
            return
        self._restoring = True
        try:
            self.resetTransform()
            self.fitInView(self._pixmap_item.boundingRect().adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)
            self._auto_fit = True
            self._emit_zoom()
        finally:
            self._restoring = False
        if user_action:
            self._notify_view()

    def actual_size(self):
        if self._pixmap_item:
            self.restore_view(ViewState(fit=False), user_action=True)

    def zoom(self, factor: float):
        if not self._pixmap_item or not math.isfinite(factor) or factor <= 0:
            return
        current = self.transform().m11() * self.devicePixelRatioF()
        target = min(16, max(.05, current * factor))
        self._auto_fit = False
        self._restoring = True
        try:
            self.scale(target / current, target / current)
        finally:
            self._restoring = False
        self._emit_zoom()
        self._notify_view()

    def _scroll_changed(self):
        if self.has_photo and not self._restoring:
            self._notify_view()

    def _notify_view(self):
        self.view_dirty = True
        self.view_changed.emit()

    def wheelEvent(self, event):
        if not self._pixmap_item:
            event.ignore()
            return
        dy = event.angleDelta().y() or event.pixelDelta().y()
        if dy:
            self.zoom(1.12 ** (max(-1200, min(1200, dy)) / 120.0))
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.has_photo:
            self._notify_view()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_photo(user_action=False)

    def _emit_zoom(self):
        self.zoom_changed.emit(round(self.transform().m11() * self.devicePixelRatioF() * 100))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
