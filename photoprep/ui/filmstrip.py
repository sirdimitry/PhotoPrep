"""Thumbnail image borders and captions occupy separate, non-overlapping areas."""
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle


class FilmstripDelegate(QStyledItemDelegate):
    def __init__(self,appearance='dark',parent=None):
        super().__init__(parent)
        self.appearance = appearance

    @staticmethod
    def regions(rect):
        image = QRect(rect.left()+8,rect.top()+2,rect.width()-16,70)
        caption = QRect(rect.left()+5,rect.top()+77,rect.width()-10,17)
        return image,caption

    def sizeHint(self,option,index):
        return QSize(140,96)

    def paint(self,painter,option,index):
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        image,caption = self.regions(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        light = self.appearance == 'light'
        painter.setBrush(QColor('#F5F6F8' if light else '#292D33'))
        painter.setPen(QPen(QColor('#FACC15' if selected else '#89929D' if hovered else '#D8DDE3' if light else '#343941'),2 if selected else 1))
        painter.drawRoundedRect(image.adjusted(1,1,-1,-1),6,6)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            icon.paint(painter,image.adjusted(4,4,-4,-4),Qt.AlignmentFlag.AlignCenter)
        painter.setPen(QColor('#26313F' if light else '#E2E6EC'))
        font = QFont(option.font)
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Normal)
        painter.setFont(font)
        text = painter.fontMetrics().elidedText(str(index.data(Qt.ItemDataRole.DisplayRole) or ''),Qt.TextElideMode.ElideRight,caption.width())
        painter.drawText(caption,Qt.AlignmentFlag.AlignCenter,text)
        painter.restore()
