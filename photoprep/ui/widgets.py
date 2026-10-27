"""Small reusable widgets for a compact photo workspace."""
from pathlib import Path
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy


class PhotoNameLabel(QLabel):
    """Two-word photo caption, elided to its allocation; full filename on hover."""
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
        path = Path(filename)
        words = list(re.finditer(r'[^\s_\-]+', path.stem))
        self._caption = (path.stem[:words[1].end()]+'…'+path.suffix) if len(words)>2 else filename
        self._update_text()

    def _update_text(self):
        self.setText(self.fontMetrics().elidedText(self._caption,Qt.TextElideMode.ElideMiddle,max(0,self.width())))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self._update_text()
