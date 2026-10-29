import time

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from photoprep.settings import Preferences
from photoprep.ui.main_window import MainWindow


def test_tools_never_reduce_photo_view_and_header_names_are_short(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=tmp_path/'Это очень длинное название фотографии для проверки.png'
    Image.new('RGB',(1600,1000),'yellow').save(source)
    window=MainWindow()
    window._confirm_discard=lambda:True
    window.resize(1100,750)
    window.show()
    app.processEvents()
    try:
        window.import_paths([str(source)])
        end=time.monotonic()+5
        while window.canvas.loading and time.monotonic()<end:
            QTest.qWait(10)
        assert not window.canvas.loading
        height=window.canvas.viewport().height()
        top=window.canvas.mapTo(window.centralWidget(),window.canvas.rect().topLeft()).y()
        assert top==50
        assert window.photo_label.toolTip()==source.name
        if window.photo_label.fontMetrics().horizontalAdvance(source.name)<=window.photo_label.width():
            assert window.photo_label.text()==source.name
        else:
            assert '...' in window.photo_label.text() and window.photo_label.text().endswith('.png')
        for language in ('ru','en'):
            prefs.language=language
            window.retranslate()
            for tool in ('mask','erase','crop','select'):
                window._select_tool(tool)
                app.processEvents()
                assert window.canvas.viewport().height()==height
                assert window.brush_slider.width()<=210
                assert window.tool_options.parentWidget().objectName()=='Inspector'
                assert window.open_files_button.height()==30
        prefs.language="ru"
        window.retranslate()
        window.resize(940,620)
        app.processEvents()
        assert window.width()==940
        assert window.photo_label.width()>40 and window.photo_label.text()
        assert window.photo_label.geometry().right()<window.open_files_button.geometry().left()
        assert not window.actual_button.geometry().intersects(window.fit_button.geometry())
    finally:
        window.canvas.clear_photo()
        window.canvas._pool.waitForDone(5000)
        window.close()
        app.processEvents()
