import time

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from photoprep.settings import Preferences
from photoprep.ui.main_window import MainWindow
from photoprep.ui.preferences_dialog import PreferencesDialog


def test_output_guides_follow_crop_zoom_and_dimensions(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=tmp_path/'A long photo caption with several words.png'
    Image.new('RGB',(800,600),'#4488CC').save(source)
    window=MainWindow()
    window._confirm_discard=lambda:True
    window.resize(1100,750)
    window.show()
    app.processEvents()
    try:
        # Enough items to require the horizontal scrollbar; captions must still fit.
        paths=[]
        for i in range(10):
            p=tmp_path/f'Image {i} caption.png'
            p.write_bytes(source.read_bytes())
            paths.append(str(p))
        window.import_paths(paths)
        end=time.monotonic()+5
        while window.canvas.loading and time.monotonic()<end: QTest.qWait(10)
        assert not window.canvas.loading
        canvas=window.canvas
        for appearance in ('dark','light'):
            prefs.appearance=appearance
            window._apply_appearance()
            for tool in ('select','mask','erase','crop'):
                window._select_tool(tool)
                app.processEvents()
                frame=canvas.output_frame_rect
                assert canvas.horizontal_ruler.position_for(0)==pytest.approx(frame.left())
                assert canvas.horizontal_ruler.position_for(1136)==pytest.approx(frame.right())
                assert canvas.vertical_ruler.value_at(frame.bottom())==pytest.approx(710)
                assert canvas.horizontal_ruler.geometry().bottom()<canvas.viewport().geometry().top()
                assert canvas.vertical_ruler.geometry().right()<canvas.viewport().geometry().left()
                # Verify the frame is actually painted, including in mask/eraser modes.
                image=canvas.viewport().grab().toImage()
                x,y=round(frame.left()),round(frame.center().y())
                ratio=image.devicePixelRatio()
                colors=[image.pixelColor(round((x+dx)*ratio),round(y*ratio)) for dx in (-1,0,1)]
                assert any(c.red()>220 and c.green()>170 and c.blue()<65 for c in colors)
            fixed=canvas.output_frame_rect
            canvas.zoom(1.5)
            assert canvas.output_frame_rect==fixed
            window._select_tool('mask')
            before=canvas.output_frame_rect
            canvas.zoom(1.2)
            assert canvas.output_frame_rect.width()==pytest.approx(before.width()*1.2)
        prefs.output_width,prefs.output_height=1920,1080
        window._preferences_applied()
        assert canvas.output_width==1920 and canvas.output_height==1080
        frame=canvas.output_frame_rect
        assert canvas.horizontal_ruler.value_at(frame.right())==pytest.approx(1920)
        assert canvas.vertical_ruler.value_at(frame.bottom())==pytest.approx(1080)
        canvas.fit_photo()
        app.processEvents()
        # Check the checkerboard pixels in a blank viewport corner.
        image=canvas.viewport().grab().toImage()
        ratio=image.devicePixelRatio()
        assert image.pixelColor(round(2*ratio),round(2*ratio))==QColor(canvas.checker_colors[1])
        assert image.pixelColor(round(10*ratio),round(2*ratio))==QColor(canvas.checker_colors[0])
        strip=window.thumbnails
        assert strip.horizontalScrollBar().maximum()>0
        image,caption=window.filmstrip_delegate.regions(strip.visualItemRect(strip.item(0)))
        assert image.bottom()+4<caption.top()
        assert caption.bottom()<strip.viewport().height()
        # The caption has text, but no yellow border can cross its row.
        image=strip.viewport().grab().toImage()
        for x in range(caption.left(),caption.right()):
            c=image.pixelColor(round(x*image.devicePixelRatio()),round(caption.center().y()*image.devicePixelRatio()))
            assert not (c.red()>220 and c.green()>170 and c.blue()<65)
    finally:
        window.canvas.clear_photo()
        window.canvas._pool.waitForDone(5000)
        window.close()
        app.processEvents()


def test_appearance_preview_cancel_save_and_restart(tmp_path):
    app=QApplication.instance() or QApplication([])
    path=str(tmp_path/'prefs.ini')
    prefs=Preferences(QSettings(path,QSettings.Format.IniFormat))
    assert prefs.appearance=='dark'
    dialog=PreferencesDialog(prefs)
    dialog.show()
    app.processEvents()
    dialog.appearance_buttons['light'].setChecked(True)
    assert dialog.selected_appearance=='light'
    assert prefs.appearance=='dark'
    dialog.reject()
    assert prefs.appearance=='dark'
    dialog=PreferencesDialog(prefs)
    dialog.appearance_buttons['light'].setChecked(True)
    dialog.apply_and_close()
    assert Preferences(QSettings(path,QSettings.Format.IniFormat)).appearance=='light'
    prefs._q.setValue('ui/appearance','invalid')
    assert prefs.appearance=='dark'
