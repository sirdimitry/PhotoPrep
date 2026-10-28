"""Brush/eraser and fixed-ratio crop interaction over a read-only photo canvas."""
from __future__ import annotations

from dataclasses import replace
import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QBrush, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsView

from ..editing import MaskStroke, CropRect, PhotoEdits, fit_crop, paint_stroke
from .canvas import PhotoCanvas
from ..workspace import ViewState
from .guides import PixelRuler, RulerCorner, RULER_SIZE


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


class EditorCanvas(PhotoCanvas):
    edits_committed = Signal(str, object)
    crop_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_pixmap = None
        self._preview_active = False
        self.tool = 'select'
        self.brush_size = 40
        self.output_width, self.output_height = 1136, 710
        self.crop_ratio = 1136 / 710
        self.edits = PhotoEdits()
        self.mask_visible = True
        self._mask_overlay = None
        self._points = None
        self._erase_stroke = False
        self._cursor_point = None
        self._pan_held = False
        self._crop_drag = None
        self._crop = None
        self._view_before_crop = None
        self._applying_image = False
        self._placing_crop = False
        self.setMouseTracking(True)
        self.appearance = 'dark'
        self.set_appearance('dark')
        self.setViewportMargins(RULER_SIZE,RULER_SIZE,0,0)
        self.horizontal_ruler = PixelRuler(self,True)
        self.vertical_ruler = PixelRuler(self,False)
        self.ruler_corner = RulerCorner(self)
        self.zoom_changed.connect(self._update_rulers)
        self.crop_changed.connect(self._update_rulers)
        self.horizontalScrollBar().valueChanged.connect(self._update_rulers)
        self.verticalScrollBar().valueChanged.connect(self._update_rulers)
        self._layout_rulers()

    def set_appearance(self,appearance):
        self.appearance = appearance
        light = appearance == 'light'
        self.guide_colors = ({'ruler':'#EDF0F4','line':'#CCD3DB','text':'#5B6675','accent':'#8E6900'} if light else
                             {'ruler':'#202328','line':'#363D47','text':'#9DA7B5','accent':'#FACC15'})
        self.checker_colors = ('#ECEFF3','#E4E8ED') if light else ('#171A1E','#1C1F24')
        tile = QPixmap(16,16)
        tile.fill(QColor(self.checker_colors[0]))
        painter = QPainter(tile)
        painter.fillRect(0,0,8,8,QColor(self.checker_colors[1]))
        painter.fillRect(8,8,8,8,QColor(self.checker_colors[1]))
        painter.end()
        self._checker_brush = QBrush(tile)
        self._update_rulers()
        self.viewport().update()

    def set_output_dimensions(self,width,height):
        self.output_width,self.output_height = width,height
        self.set_crop_ratio(width/height)

    @property
    def output_frame_rect(self):
        """Show the planned result in source view; anchor it while editing the crop."""
        if not self.has_photo:
            return QRectF()
        if self.tool == 'crop':
            return self.crop_frame_rect
        bounds = self._pixmap_item.boundingRect()
        source = (self.edits.crop or self._default_crop()).pixels(bounds.width(),bounds.height())
        return self.viewportTransform().mapRect(source)

    def _layout_rulers(self):
        if not hasattr(self,'horizontal_ruler'):
            return
        viewport = self.viewport().geometry()
        self.horizontal_ruler.setGeometry(viewport.x(),0,viewport.width(),RULER_SIZE)
        self.vertical_ruler.setGeometry(0,viewport.y(),RULER_SIZE,viewport.height())
        self.ruler_corner.setGeometry(0,0,RULER_SIZE,RULER_SIZE)
        self._update_rulers()

    def _update_rulers(self,*args):
        for name in ('horizontal_ruler','vertical_ruler','ruler_corner'):
            widget = getattr(self,name,None)
            if widget is not None:
                widget.update()

    def drawBackground(self,painter,rect):
        painter.save()
        painter.resetTransform()
        painter.fillRect(self.viewport().rect(),self._checker_brush)
        painter.restore()

    def _clear_image(self):
        self.finish_edit()
        self._mask_overlay = None
        self._original_pixmap = None
        self._preview_active = False
        self._cursor_point = None
        self._crop_drag = None
        self._crop = None
        self._view_before_crop = None
        self.edits = PhotoEdits()
        self._restoring = True
        try:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setSceneRect(QRectF())
            super()._clear_image()
        finally:
            self._restoring = False
        self._update_rulers()

    def _apply_image(self, path, image):
        self._original_pixmap = QPixmap.fromImage(image)
        self._preview_active = False
        self._applying_image = True
        try:
            super()._apply_image(path, image)
        finally:
            self._applying_image = False
        self._mask_overlay = MaskOverlay(image.width(), image.height())
        self.scene().addItem(self._mask_overlay)
        self.set_edits(self.edits)
        self.set_tool(self.tool)
        self._update_rulers()

    def set_preview(self,image=None):
        if not self.has_photo or self._original_pixmap is None:
            return
        if image is not None and image.size()!=self._original_pixmap.size():
            raise ValueError('Preview dimensions do not match source')
        self._preview_active = image is not None
        self._pixmap_item.setPixmap(QPixmap.fromImage(image) if image is not None else self._original_pixmap)
        if self._mask_overlay:
            self._mask_overlay.setVisible(self.mask_visible and (not self._preview_active or self.tool in ('mask','erase')))
        self.viewport().update()

    def set_edits(self, edits):
        self.edits = edits
        self._points = None
        if self._mask_overlay:
            self._mask_overlay.rebuild(edits.strokes)
            self._mask_overlay.setVisible(self.mask_visible and (not self._preview_active or self.tool in ('mask','erase')))
        if self.tool == 'crop' and self.has_photo and not self._applying_image:
            self._enter_crop()
        self.crop_changed.emit()
        self.viewport().update()

    @property
    def crop_frame_rect(self):
        """The fixed output frame in viewport coordinates, independent of the image."""
        available = QRectF(self.viewport().rect()).adjusted(24,24,-24,-24)
        width = min(max(1,available.width()), max(1,available.height()) * self.crop_ratio)
        height = width / self.crop_ratio
        center = available.center()
        return QRectF(center.x()-width/2,center.y()-height/2,width,height)

    @property
    def crop_rect(self):
        return self._crop

    def _default_crop(self):
        bounds = self._pixmap_item.boundingRect()
        return fit_crop(round(bounds.width()),round(bounds.height()),self.crop_ratio)

    def _enter_crop(self):
        if self._view_before_crop is None:
            self._view_before_crop = super().view_state()
        self._place_crop(self.edits.crop or self._default_crop())

    def _place_crop(self, crop):
        if not self.has_photo or self._placing_crop:
            return
        self._placing_crop = True
        self._restoring = True
        try:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            bounds = self._pixmap_item.boundingRect()
            margin = max(bounds.width(),bounds.height())*4
            self.setSceneRect(bounds.adjusted(-margin,-margin,margin,margin))
            frame = self.crop_frame_rect
            rect = crop.pixels(bounds.width(),bounds.height())
            scale = frame.width()/rect.width()
            self.resetTransform()
            self.scale(scale,scale)
            self.centerOn(rect.center())
            self._auto_fit = False
            self._crop = crop
            self._emit_zoom()
        finally:
            self._restoring = False
            self._placing_crop = False
        self.crop_changed.emit()
        self.viewport().update()
        self.viewport().update()

    def _leave_crop(self):
        self._restoring = True
        try:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            if self.has_photo:
                self.setSceneRect(self._pixmap_item.boundingRect())
                super().restore_view(self._view_before_crop or ViewState())
        finally:
            self._restoring = False
        self._view_before_crop = None

    def view_state(self):
        if self.tool == 'crop' and self._view_before_crop is not None:
            return self._view_before_crop
        return super().view_state()

    def set_tool(self, tool):
        if tool not in ('select','mask','erase','crop'):
            raise ValueError('Unknown editing tool')
        self.finish_edit()
        previous_tool = self.tool
        self.tool = tool
        if previous_tool == 'crop' and tool != 'crop':
            self._leave_crop()
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if tool == 'select' else QGraphicsView.DragMode.NoDrag)
        if tool == 'crop' and self.has_photo and not self._applying_image:
            self._enter_crop()
        self._cursor_point = None
        if self._mask_overlay:
            self._mask_overlay.setVisible(self.mask_visible and (not self._preview_active or self.tool in ("mask","erase")))
        self._update_cursor()
        self.viewport().update()

    def set_crop_ratio(self, ratio):
        self.crop_ratio = ratio
        if self.tool == 'crop' and self.has_photo and not self._applying_image:
            self._enter_crop()
        self.crop_changed.emit()
        self.viewport().update()

    def set_brush_size(self, value):
        self.brush_size = max(2,min(512,int(value)))
        self.viewport().update()

    def set_mask_visible(self, value):
        self.mask_visible = value
        if self._mask_overlay:
            self._mask_overlay.setVisible(value and (not self._preview_active or self.tool in ('mask','erase')))

    def _commit(self, edits):
        if edits != self.edits and self.current_path:
            self.edits = edits
            self.edits_committed.emit(self.current_path,edits)

    def clear_mask(self):
        self._finish_stroke()
        self._commit(replace(self.edits,strokes=()))
        self.set_edits(self.edits)

    def reset_crop(self):
        if self.has_photo:
            current = self._crop or self.edits.crop or self._default_crop()
            crop = self._crop_centered(current.width,current.height,.5,.5)
            self._commit(replace(self.edits,crop=crop))
            if self.tool == 'crop':
                self._place_crop(crop)

    def clear_crop(self):
        self._commit(replace(self.edits,crop=None))
        if self.tool == 'crop' and self.has_photo:
            self._place_crop(self._default_crop())

    @staticmethod
    def _crop_centered(width,height,cx,cy):
        return CropRect(min(1-width,max(0,cx-width/2)), min(1-height,max(0,cy-height/2)),width,height)

    def fit_crop_view(self):
        if self.tool != 'crop' or not self.has_photo:
            return
        default = self._default_crop()
        old = self._crop or default
        crop = self._crop_centered(default.width,default.height,old.x+old.width/2,old.y+old.height/2)
        self._place_crop(crop)
        self._commit(replace(self.edits,crop=crop))

    def fit_photo(self, *, user_action=True):
        if getattr(self,'tool','select') == 'crop' and self.has_photo and not self._applying_image:
            if user_action:
                self.fit_crop_view()
            elif self._crop is not None:
                self._place_crop(self._crop)
        else:
            super().fit_photo(user_action=user_action)

    def actual_size(self):
        if self.tool == 'crop' and self.has_photo:
            self.zoom(1/(self.transform().m11()*self.devicePixelRatioF()))
        else:
            super().actual_size()

    def zoom(self, factor):
        if self.tool != 'crop' or not self.has_photo:
            return super().zoom(factor)
        if not math.isfinite(factor) or factor <= 0:
            return
        bounds, frame = self._pixmap_item.boundingRect(),self.crop_frame_rect
        minimum = max(frame.width()/bounds.width(),frame.height()/bounds.height())*self.devicePixelRatioF()
        current = self.transform().m11()*self.devicePixelRatioF()
        target = max(minimum,min(max(16,minimum),current*factor))
        scale = target/self.devicePixelRatioF()
        width,height = frame.width()/scale/bounds.width(),frame.height()/scale/bounds.height()
        old = self._crop or self._default_crop()
        crop = self._crop_centered(min(1,width),min(1,height),old.x+old.width/2,old.y+old.height/2)
        self._place_crop(crop)
        self._commit(replace(self.edits,crop=crop))

    def _normalized(self, point):
        bounds = self._pixmap_item.boundingRect()
        return point.x()/bounds.width(),point.y()/bounds.height()

    def _stroke(self, points):
        bounds = self._pixmap_item.boundingRect()
        return MaskStroke(tuple(points),self.brush_size/min(bounds.width(),bounds.height()),self._erase_stroke)

    def _finish_stroke(self):
        if self._points and self._pixmap_item:
            stroke = self._stroke(self._points)
            self._points = None
            self._commit(replace(self.edits,strokes=self.edits.strokes+(stroke,)))
        self._points = None

    def finish_edit(self):
        self._finish_stroke()
        if self._crop_drag is not None and self._crop is not None:
            self._crop_drag = None
            self._commit(replace(self.edits,crop=self._crop))

    def mousePressEvent(self,event):
        if self.has_photo and event.button()==Qt.MouseButton.LeftButton:
            if self.tool == 'crop':
                self._crop_drag = (event.position(),self._crop or self._default_crop())
                self._update_cursor()
                event.accept()
                return
            point = self.mapToScene(event.position().toPoint())
            if not self._pan_held and self.tool in ('mask','erase') and self._pixmap_item.boundingRect().contains(point):
                self._erase_stroke = self.tool == 'erase'
                self._points = [self._normalized(point)]
                self._mask_overlay.add_stroke(self._stroke(self._points))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        point = self.mapToScene(event.position().toPoint())
        self._cursor_point = point if self.has_photo else None
        if self._crop_drag is not None:
            start,old = self._crop_drag
            delta = event.position()-start
            bounds = self._pixmap_item.boundingRect()
            scale = self.transform().m11()
            x = old.x-delta.x()/scale/bounds.width()
            y = old.y-delta.y()/scale/bounds.height()
            self._place_crop(CropRect(min(1-old.width,max(0,x)),min(1-old.height,max(0,y)),old.width,old.height))
            event.accept()
        elif self._points is not None and self.has_photo:
            normalized,previous = self._normalized(point),self._points[-1]
            bounds = self._pixmap_item.boundingRect()
            if math.hypot((normalized[0]-previous[0])*bounds.width(),(normalized[1]-previous[1])*bounds.height())>=1:
                self._points.append(normalized)
                self._mask_overlay.add_stroke(self._stroke((previous,normalized)))
            event.accept()
        else:
            super().mouseMoveEvent(event)
        self._update_cursor()
        self.viewport().update()

    def mouseReleaseEvent(self,event):
        if self._points is not None or self._crop_drag is not None:
            self.finish_edit()
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():
            self.finish_edit()
            self._pan_held = True
            if self.tool != 'crop':
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._update_cursor()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self,event):
        if event.key()==Qt.Key.Key_Space and not event.isAutoRepeat():
            self._pan_held = False
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if self.tool=='select' else QGraphicsView.DragMode.NoDrag)
            self._update_cursor()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self,event):
        self.finish_edit()
        self._pan_held = False
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if self.tool=='select' else QGraphicsView.DragMode.NoDrag)
        self._update_cursor()
        super().focusOutEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if getattr(self,'tool','select')=='crop' and self.has_photo and self._crop is not None:
            self._place_crop(self._crop)
        self._layout_rulers()

    def leaveEvent(self,event):
        self._cursor_point = None
        self.viewport().update()
        super().leaveEvent(event)

    def _update_cursor(self):
        if not self.has_photo:
            cursor=Qt.CursorShape.ArrowCursor
        elif self.tool=='crop':
            cursor=Qt.CursorShape.ClosedHandCursor if self._crop_drag is not None else Qt.CursorShape.OpenHandCursor
        elif self._pan_held or self.tool=='select':
            cursor=Qt.CursorShape.OpenHandCursor
        else:
            cursor=Qt.CursorShape.BlankCursor if self._cursor_point is not None else Qt.CursorShape.CrossCursor
        self.viewport().setCursor(cursor)

    def drawForeground(self,painter,rect):
        super().drawForeground(painter,rect)
        if self.has_photo:
            painter.save()
            painter.resetTransform()
            frame,bounds=self.output_frame_rect,QRectF(self.viewport().rect())
            if self.tool=='crop':
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0,0,0,95 if self.appearance=='light' else 135))
                for outside in (QRectF(0,0,bounds.width(),frame.top()),
                                QRectF(0,frame.bottom(),bounds.width(),bounds.height()-frame.bottom()),
                                QRectF(0,frame.top(),frame.left(),frame.height()),
                                QRectF(frame.right(),frame.top(),bounds.width()-frame.right(),frame.height())):
                    painter.drawRect(outside)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0,0,0,155),3.5))
            painter.drawRect(frame)
            painter.setPen(QPen(QColor('#FACC15'),1.8))
            painter.drawRect(frame)
            if self.tool=='crop':
                painter.setPen(QPen(QColor(255,255,255,110),1))
                for fraction in (1/3,2/3):
                    painter.drawLine(QPointF(frame.left()+frame.width()*fraction,frame.top()),QPointF(frame.left()+frame.width()*fraction,frame.bottom()))
                    painter.drawLine(QPointF(frame.left(),frame.top()+frame.height()*fraction),QPointF(frame.right(),frame.top()+frame.height()*fraction))
            painter.restore()
        if self.has_photo and self.tool in ('mask','erase') and self._cursor_point is not None and not self._pan_held:
            pen=QPen(QColor('#FFFFFF'),1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self._cursor_point,self.brush_size/2,self.brush_size/2)
