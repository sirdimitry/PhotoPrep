"""Small reusable widgets for a compact photo workspace."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedWidget


class PhotoNameLabel(QLabel):
    """Full filename, middle-elided only when its allocated width is insufficient."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._caption = ''
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setObjectName('HeaderPhotoName')

    def set_filename(self, filename):
        self.setToolTip(filename)
        self.setAccessibleName(filename)
        self._caption = filename
        self._update_text()

    def _update_text(self):
        metrics=self.fontMetrics();width=max(0,self.contentsRect().width())
        if metrics.horizontalAdvance(self._caption)<=width:
            self.setText(self._caption);return
        def shortened(count):
            left=(count+1)//2;right=count//2
            return self._caption[:left]+'...'+(self._caption[-right:] if right else '')
        low,high=0,len(self._caption)
        while low<high:
            middle=(low+high+1)//2
            if metrics.horizontalAdvance(shortened(middle))<=width:low=middle
            else:high=middle-1
        self.setText(shortened(low) if metrics.horizontalAdvance('...')<=width else '')

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._update_text()


class ToolOptions(QStackedWidget):
    """Use the active tool's height instead of the tallest hidden tool page."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self.updateGeometry)

    def sizeHint(self):
        page=self.currentWidget()
        if page is None:return super().sizeHint()
        hint=page.sizeHint()
        if page.hasHeightForWidth():
            height=page.heightForWidth(max(1,self.width()))
            if height>=0:hint.setHeight(height)
        return hint

    def minimumSizeHint(self):
        return self.sizeHint()
