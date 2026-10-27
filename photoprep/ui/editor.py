"""Brush/eraser and fixed-ratio crop interaction over a read-only photo canvas."""
from __future__ import annotations

from dataclasses import replace
import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsView

from ..editing import MaskStroke, CropRect, PhotoEdits, fit_crop, paint_stroke
from .canvas import PhotoCanvas


class MaskOverlay(QGraphicsItem):
    def __init__(self, width, height):
        super().__init__()
        self.width, self.height = width, height
        scale = min(1, 1536 / max(width, height))
        self.image = QImage(max(1, round(width * scale)), max(1, round(height * scale)), QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.GlobalColor.transparent)
        self.setZValue(10)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.boundingRect(), self.image)

    def add_stroke(self, stroke):
        painter = QPainter(self.image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_stroke(painter, stroke, self.image.width(), self.image.height(), overlay=True)
        painter.end()
        self.update()

    def rebuild(self, strokes):
        self.image.fill(Qt.GlobalColor.transparent)
        for stroke in strokes:
            self.add_stroke(stroke)
        self.update()


class CropOverlay(QGraphicsItem):
    def __init__(self, width, height):
        super().__init__()
        self.width, self.height = width, height
        self.crop = fit_crop(width, height, 1136 / 710)
        self.setZValue(20)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        rect = self.crop.pixels(self.width, self.height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 125))
        for outside in (QRectF(0, 0, self.width, rect.top()),
                        QRectF(0, rect.bottom(), self.width, self.height - rect.bottom()),
                        QRectF(0, rect.top(), rect.left(), rect.height()),
                        QRectF(rect.right(), rect.top(), self.width - rect.right(), rect.height())):
            painter.drawRect(outside)
        pen = QPen(QColor('#FACC15'), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        grid_pen = QPen(QColor(255, 255, 255, 130), 1)
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)
        for fraction in (1/3, 2/3):
            painter.drawLine(QPointF(rect.left()+rect.width()*fraction, rect.top()), QPointF(rect.left()+rect.width()*fraction, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), rect.top()+rect.height()*fraction), QPointF(rect.right(), rect.top()+rect.height()*fraction))
        scale = max(.001, abs(painter.transform().m11()))
        radius = 4 / scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#FACC15'))
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawRect(QRectF(point.x()-radius, point.y()-radius, radius*2, radius*2))


class EditorCanvas(PhotoCanvas):
    edits_committed = Signal(str, object)
    crop_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tool = 'select'
        self.brush_size = 40
        self.crop_ratio = 1136 / 710
        self.edits = PhotoEdits()
        self.mask_visible = True
        self._mask_overlay = None
        self._crop_overlay = None
        self._points = None
        self._erase_stroke = False
        self._cursor_point = None
        self._pan_held = False
        self._crop_drag = None
        self._crop_before = None
        self.setMouseTracking(True)

    def _clear_image(self):
        self._finish_stroke()
        self._mask_overlay = self._crop_overlay = None
        self._cursor_point = None
        self._crop_drag = None
        self.edits = PhotoEdits()
        super()._clear_image()

    def _apply_image(self, path, image):
        super()._apply_image(path, image)
        self._mask_overlay = MaskOverlay(image.width(), image.height())
        self._crop_overlay = CropOverlay(image.width(), image.height())
        self.scene().addItem(self._mask_overlay)
        self.scene().addItem(self._crop_overlay)
        self.set_edits(self.edits)
        self.set_tool(self.tool)

    def set_edits(self, edits):
        self.edits = edits
        self._points = None
        if self._mask_overlay:
            self._mask_overlay.rebuild(edits.strokes)
            self._mask_overlay.setVisible(self.mask_visible)
        if self._crop_overlay:
            self._crop_overlay.crop = edits.crop or fit_crop(self._crop_overlay.width, self._crop_overlay.height, self.crop_ratio)
            self._crop_overlay.setVisible(self.tool == 'crop')
            self._crop_overlay.update()
        self.crop_changed.emit()

    def set_tool(self, tool):
        if tool not in ('select', 'mask', 'erase', 'crop'):
            raise ValueError('Unknown editing tool')
        self._finish_stroke()
        self.tool = tool
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if tool == 'select' else QGraphicsView.DragMode.NoDrag)
        if self._crop_overlay:
            self._crop_overlay.setVisible(tool == 'crop')
        self._cursor_point = None
        self._update_cursor()
        self.viewport().update()

    def set_crop_ratio(self, ratio):
        self.crop_ratio = ratio
        if self._crop_overlay:
            self._crop_overlay.crop = fit_crop(self._crop_overlay.width, self._crop_overlay.height, ratio, self.edits.crop)
            self._crop_overlay.update()
        self.crop_changed.emit()

    def set_brush_size(self, value):
        self.brush_size = max(2, min(512, int(value)))
        self.viewport().update()

    def set_mask_visible(self, value):
        self.mask_visible = value
        if self._mask_overlay:
            self._mask_overlay.setVisible(value)

    def _commit(self, edits):
        if edits != self.edits and self.current_path:
            self.edits = edits
            self.edits_committed.emit(self.current_path, edits)

    def clear_mask(self):
        self._finish_stroke()
        self._commit(replace(self.edits, strokes=()))
        self.set_edits(self.edits)

    def reset_crop(self):
        if self._crop_overlay:
            crop = fit_crop(self._crop_overlay.width, self._crop_overlay.height, self.crop_ratio)
            self._commit(replace(self.edits, crop=crop))
            self.set_edits(self.edits)

    def clear_crop(self):
        self._commit(replace(self.edits, crop=None))
        self.set_edits(self.edits)

    def fit_crop_view(self):
        if self._crop_overlay:
            self._restoring = True
            try:
                self.fitInView(self._crop_overlay.crop.pixels(self._crop_overlay.width, self._crop_overlay.height).adjusted(-12,-12,12,12), Qt.AspectRatioMode.KeepAspectRatio)
                self._auto_fit = False
            finally:
                self._restoring = False
            self._emit_zoom()
            self._notify_view()

    def _normalized(self, point):
        bounds = self._pixmap_item.boundingRect()
        return point.x()/bounds.width(), point.y()/bounds.height()

    def _stroke(self, points):
        bounds = self._pixmap_item.boundingRect()
        return MaskStroke(tuple(points), self.brush_size/min(bounds.width(), bounds.height()), self._erase_stroke)

    def _finish_stroke(self):
        if self._points and self._pixmap_item:
            stroke = self._stroke(self._points)
            self._points = None
            self._commit(replace(self.edits, strokes=self.edits.strokes+(stroke,)))
        self._points = None

    def _crop_hit(self, point):
        rect = self._crop_overlay.crop.pixels(self._crop_overlay.width, self._crop_overlay.height)
        radius = 12 / max(.001, self.transform().m11())
        for corner, handle in (('tl',rect.topLeft()),('tr',rect.topRight()),('bl',rect.bottomLeft()),('br',rect.bottomRight())):
            if math.hypot(point.x()-handle.x(), point.y()-handle.y()) <= radius:
                return corner
        return 'move' if rect.contains(point) else None

    def _move_crop(self, point):
        overlay = self._crop_overlay
        start_point, original, mode = self._crop_drag
        rect = original.pixels(overlay.width, overlay.height)
        if mode == 'move':
            dx, dy = point.x()-start_point.x(), point.y()-start_point.y()
            x = min(overlay.width-rect.width(), max(0, rect.x()+dx))
            y = min(overlay.height-rect.height(), max(0, rect.y()+dy))
            crop = CropRect(x/overlay.width,y/overlay.height,original.width,original.height)
        else:
            anchor = {'tl':rect.bottomRight(),'tr':rect.bottomLeft(),'bl':rect.topRight(),'br':rect.topLeft()}[mode]
            sx, sy = (-1 if 'l' in mode else 1), (-1 if 't' in mode else 1)
            # Project the pointer onto the fixed-ratio corner diagonal.
            ratio = self.crop_ratio
            h = max(8, (sx*(point.x()-anchor.x())*ratio + sy*(point.y()-anchor.y())) / (ratio*ratio+1))
            limit_w = anchor.x() if sx<0 else overlay.width-anchor.x()
            limit_h = anchor.y() if sy<0 else overlay.height-anchor.y()
            h = min(h, limit_h, limit_w/ratio)
            w = h*ratio
            x, y = (anchor.x()-w if sx<0 else anchor.x()), (anchor.y()-h if sy<0 else anchor.y())
            crop = CropRect(x/overlay.width,y/overlay.height,w/overlay.width,h/overlay.height)
        overlay.crop = crop
        overlay.update()
        self.crop_changed.emit()

    def mousePressEvent(self, event):
        if self.has_photo and event.button() == Qt.MouseButton.LeftButton and not self._pan_held:
            point = self.mapToScene(event.position().toPoint())
            if self.tool in ('mask','erase') and self._pixmap_item.boundingRect().contains(point):
                self._erase_stroke = self.tool == 'erase'
                self._points = [self._normalized(point)]
                self._mask_overlay.add_stroke(self._stroke(self._points))
                event.accept()
                return
            if self.tool == 'crop' and self._crop_overlay:
                hit = self._crop_hit(point)
                if hit:
                    self._crop_before = self.edits.crop
                    self._crop_drag = (point,self._crop_overlay.crop,hit)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        self._cursor_point = point if self.has_photo else None
        if self._points is not None and self.has_photo:
            normalized = self._normalized(point)
            previous = self._points[-1]
            bounds = self._pixmap_item.boundingRect()
            if math.hypot((normalized[0]-previous[0])*bounds.width(),(normalized[1]-previous[1])*bounds.height()) >= 1:
                self._points.append(normalized)
                self._mask_overlay.add_stroke(self._stroke((previous,normalized)))
            event.accept()
        elif self._crop_drag is not None:
            self._move_crop(point)
            event.accept()
        else:
            super().mouseMoveEvent(event)
        self._update_cursor()
        self.viewport().update()

    def mouseReleaseEvent(self, event):
        if self._points is not None:
            self._finish_stroke()
            event.accept()
            return
        if self._crop_drag is not None:
            self._commit(replace(self.edits,crop=self._crop_overlay.crop))
            self._crop_drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():
            self._finish_stroke()
            self._pan_held=True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._update_cursor()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():
            self._pan_held=False
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if self.tool=='select' else QGraphicsView.DragMode.NoDrag)
            self._update_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def leaveEvent(self, event):
        self._cursor_point=None
        self.viewport().update()
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        self._finish_stroke()
        if self._crop_drag is not None and self._crop_overlay:
            self._commit(replace(self.edits,crop=self._crop_overlay.crop))
            self._crop_drag = None
        self._pan_held = False
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if self.tool=='select' else QGraphicsView.DragMode.NoDrag)
        self._update_cursor()
        super().focusOutEvent(event)

    def _update_cursor(self):
        if not self.has_photo:
            cursor=Qt.CursorShape.ArrowCursor
        elif self._pan_held or self.tool=='select':
            cursor=Qt.CursorShape.OpenHandCursor
        elif self.tool in ('mask','erase'):
            cursor=Qt.CursorShape.BlankCursor if self._cursor_point is not None else Qt.CursorShape.CrossCursor
        elif self._crop_overlay and self._cursor_point is not None:
            hit=self._crop_hit(self._cursor_point)
            cursor=(Qt.CursorShape.SizeFDiagCursor if hit in ('tl','br') else
                    Qt.CursorShape.SizeBDiagCursor if hit in ('tr','bl') else
                    Qt.CursorShape.SizeAllCursor if hit=='move' else Qt.CursorShape.ArrowCursor)
        else:
            cursor=Qt.CursorShape.CrossCursor
        self.viewport().setCursor(cursor)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter,rect)
        if self.has_photo and self.tool in ('mask','erase') and self._cursor_point is not None and not self._pan_held:
            pen=QPen(QColor('#FFFFFF'),1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            radius=self.brush_size/2
            painter.drawEllipse(self._cursor_point,radius,radius)
