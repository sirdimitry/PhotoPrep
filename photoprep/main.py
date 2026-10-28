"""Launch the PhotoPrep desktop application."""
from __future__ import annotations
import sys

from PySide6.QtCore import Qt,QCoreApplication,QEvent,QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .ui.assets import app_icon_path


def main() -> int:
    if len(sys.argv)>1 and sys.argv[1]=="--photoprep-worker":
        from .inference import worker_main
        return worker_main(sys.argv[2:])
    from .ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("sirdimitry")
    app.setApplicationName("PhotoPrep")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(app_icon_path()))
    window = MainWindow()
    window.show()
    if '--verify-startup' in sys.argv:
        from .ui.export_dialog import ExportDialog
        dialog=ExportDialog(window.workspace,window.settings,window)
        window._export_dialog=dialog
        dialog.finished.connect(lambda result:setattr(window,'_export_dialog',None))
        dialog.show()
        QTimer.singleShot(150,dialog.reject)
        QTimer.singleShot(350,window.close)
    result=app.exec()
    window.shutdown()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
