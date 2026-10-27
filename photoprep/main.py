"""Launch the PhotoPrep desktop application."""
from __future__ import annotations
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .ui.assets import app_icon_path
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("sirdimitry")
    app.setApplicationName("PhotoPrep")
    app.setApplicationVersion("0.1.0-alpha.1")
    app.setWindowIcon(QIcon(app_icon_path()))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
