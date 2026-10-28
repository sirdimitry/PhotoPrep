"""Keep one QApplication alive and destroy test widgets before Python finalizes."""
import pytest
import ctypes
import os
from shiboken6 import isValid

_guard=None

def pytest_sessionstart(session):
    global _guard
    path=os.environ.get("PHOTOPREP_TEST_CRASH_GUARD")
    if path:
        _guard=ctypes.CDLL(path)
        _guard.install_test_crash_guard()
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='session',autouse=True)
def qt_application_lifetime():
    application=QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    yield application
    for widget in list(application.topLevelWidgets()):
        if not isValid(widget):continue
        if hasattr(widget,'_confirm_discard'):widget._confirm_discard=lambda:True
        if hasattr(widget,'shutdown'):widget.shutdown()
        if hasattr(widget,'_shutdown'):widget._shutdown()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    application.processEvents()
