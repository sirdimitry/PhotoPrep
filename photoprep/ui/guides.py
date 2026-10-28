"""Pixel rulers aligned with the output frame, without adding a toolbar."""
import math

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

RULER_SIZE = 22


def major_step(pixels_per_unit):
    desired = 64 / max(1e-9, pixels_per_unit)
    power = 10 ** math.floor(math.log10(desired))
    return next(multiplier * power for multiplier in (1, 2, 5, 10) if multiplier * power >= desired)


class PixelRuler(QWidget):
    def __init__(self, canvas, horizontal):
        super().__init__(canvas)
        self.canvas = canvas
        self.horizontal = horizontal
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAccessibleName('Horizontal pixel ruler' if horizontal else 'Vertical pixel ruler')

    def mapping(self):
        frame = self.canvas.output_frame_rect
        if frame.isEmpty():
            return None
        origin = frame.left() if self.horizontal else frame.top()
        extent = frame.width() if self.horizontal else frame.height()
        units = self.canvas.output_width if self.horizontal else self.canvas.output_height
        return origin, extent / units, units

    def position_for(self, value):
        mapping = self.mapping()
        return mapping[0] + value * mapping[1] if mapping else None

    def value_at(self, position):
        mapping = self.mapping()
        return (position-mapping[0])/mapping[1] if mapping else None

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = self.canvas.guide_colors
        painter.fillRect(self.rect(), QColor(colors['ruler']))
        painter.setPen(QColor(colors['line']))
        if self.horizontal:
            painter.drawLine(0,self.height()-1,self.width(),self.height()-1)
        else:
            painter.drawLine(self.width()-1,0,self.width()-1,self.height())
        mapping = self.mapping()
        if mapping is None:
            return
        origin, scale, units = mapping
        length = self.width() if self.horizontal else self.height()
        step = major_step(scale)
        minor = step / 5
        start = math.floor((-origin/scale)/minor)
        stop = math.ceil(((length-origin)/scale)/minor)
        painter.setFont(QFont('Helvetica Neue', 8))
        painter.setPen(QColor(colors['text']))
        for index in range(start,stop+1):
            value = index*minor
            position = origin+value*scale
            major = index % 5 == 0
            if self.horizontal:
                painter.drawLine(round(position),self.height()-1,round(position),self.height()-(7 if major else 4))
            else:
                painter.drawLine(self.width()-1,round(position),self.width()-(7 if major else 4),round(position))
            near_endpoint = min(abs(position-origin),abs(position-(origin+units*scale))) < 30
            if major and not near_endpoint:
                self._label(painter,position,value)
        # Always show exact output edges, even when they are not round numbers.
        painter.setPen(QColor(colors['accent']))
        for value in (0,units):
            position = origin+value*scale
            if 0 <= position <= length:
                if self.horizontal:
                    painter.drawLine(round(position),self.height()-1,round(position),self.height()-8)
                else:
                    painter.drawLine(self.width()-1,round(position),self.width()-8,round(position))
                self._label(painter,position,value)

    def _label(self,painter,position,value):
        text = str(round(value)) if abs(value-round(value)) < 1e-7 else f'{value:g}'
        width = painter.fontMetrics().horizontalAdvance(text)
        if self.horizontal:
            x = max(1,min(self.width()-width-1,position-width/2))
            painter.drawText(QRectF(x,0,width+1,13),Qt.AlignmentFlag.AlignCenter,text)
        else:
            painter.save()
            y = max(width/2+1,min(self.height()-width/2-1,position))
            painter.translate(11,y)
            painter.rotate(-90)
            painter.drawText(QRectF(-width/2,-10,width+1,13),Qt.AlignmentFlag.AlignCenter,text)
            painter.restore()


class RulerCorner(QWidget):
    def __init__(self,canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.fillRect(self.rect(),QColor(self.canvas.guide_colors['ruler']))
        painter.setPen(QColor(self.canvas.guide_colors['text']))
        painter.setFont(QFont('Helvetica Neue',8))
        painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'px')
