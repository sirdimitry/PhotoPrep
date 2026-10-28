from dataclasses import replace
import time
from pathlib import Path
from PIL import Image,ImageDraw
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage,QColor
from photoprep.editing import MaskStroke
from photoprep.settings import Preferences
from photoprep.ui.main_window import MainWindow
from photoprep.ui.export_dialog import ExportDialog


def wait(predicate):
    end=time.monotonic()+12
    while not predicate() and time.monotonic()<end:QTest.qWait(10)
    assert predicate()


def window(tmp_path,monkeypatch,count=2):
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat));prefs.language='ru';prefs.output_width=160;prefs.output_height=128
    folder=tmp_path/'templates';folder.mkdir()
    template=folder/'left.png';image=Image.new('RGBA',(1920,1080));ImageDraw.Draw(image).rectangle((76,67,395,185),fill='white');image.save(template)
    prefs.logo_folder=str(folder);monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    photos=[]
    for i in range(count):
        parent=tmp_path/str(i);parent.mkdir();path=parent/('source.jpg' if i%2 else 'source.png');Image.new('RGB',(320,200),'blue').save(path);photos.append(path)
    w=MainWindow();w._confirm_discard=lambda:True;w.show();w.import_paths([str(p) for p in photos]);wait(lambda:not w.canvas.loading);w._select_tool('logo')
    return w,photos,template


def test_switching_photo_does_not_show_previous_logo_settings(tmp_path,monkeypatch,qt_application_lifetime):
    w,photos,template=window(tmp_path,monkeypatch)
    try:
        w._choose_catalog_logo(1);assert w.logo_library.currentIndex()==1 and w.logo_details.isVisible()
        first=w.workspace.edits[photos[0]].logo
        w.select_photo(1);wait(lambda:not w.canvas.loading)
        assert w.workspace.edits[photos[1]].logo is None and w.canvas.edits.logo is None
        assert w.logo_library.currentIndex()==0 and not w.logo_details.isVisible()
        assert w.logo_empty.isVisible() and w.logo_all.isEnabled()
        w.select_photo(0);wait(lambda:not w.canvas.loading)
        assert w.logo_library.currentIndex()==1 and w.logo_details.isVisible()
        assert w.canvas.edits.logo==first and w.canvas._logo_overlay.isVisible()
    finally:w.close()


def test_enable_all_from_unbranded_photo_preserves_placement_and_updates_canvas(tmp_path,monkeypatch,qt_application_lifetime):
    w,photos,template=window(tmp_path,monkeypatch)
    try:
        w._choose_catalog_logo(1);logo=replace(w.workspace.edits[photos[0]].logo,width=.23,x=.7,y=.15,opacity=.6,enabled=False)
        w._set_logo(logo)
        w.select_photo(1);wait(lambda:not w.canvas.loading)
        retouch=replace(w.workspace.edits[photos[1]],passes=((MaskStroke(((.5,.5),),.1),),))
        w.workspace.set_edits(photos[1],retouch);w.canvas.set_edits(retouch)
        processed=QImage(320,200,QImage.Format.Format_RGBA8888);processed.fill(QColor('green'))
        w._previews[w._preview_key()]=processed;w._show_preview(True)
        w.logo_all.click()
        assert w.canvas._preview_active and w.canvas._pixmap_item.pixmap().toImage().pixelColor(0,0)==QColor('green')
        assert w.workspace.edits[photos[1]].passes==retouch.passes
        expected=replace(logo,enabled=True)
        assert all(w.workspace.edits[p].logo==expected for p in photos)
        assert w.canvas.edits.logo==expected and w.canvas._logo_overlay.isVisible()
        assert w.logo_details.isVisible() and w.logo_enabled.isChecked()
        w.undo();wait(lambda:not w.canvas.loading)
        assert w.workspace.edits[photos[0]].logo==logo and w.workspace.edits[photos[1]].logo is None
        assert not w.logo_details.isVisible() and w.logo_library.currentIndex()==0
        w.redo();wait(lambda:not w.canvas.loading)
        assert w.canvas.edits.logo==expected and w.canvas._logo_overlay.isVisible()
    finally:w.close()


@pytest.mark.parametrize('format,suffix',[('JPEG','.jpg'),('PNG','.png')])
def test_export_defaults_to_entire_collection_with_one_format(tmp_path,monkeypatch,qt_application_lifetime,format,suffix):
    w,photos,template=window(tmp_path,monkeypatch,count=3)
    try:
        w._choose_catalog_logo(1);w.logo_all.click()
        dialog=ExportDialog(w.workspace,w.settings,w)
        assert dialog.all.isChecked() and len(dialog.selected_photos)==3
        assert '3' in dialog.start_button.text()
        dialog.formats[format].setChecked(True);dialog.start();wait(lambda:not dialog.busy and dialog._finished_once)
        assert not dialog._error and not dialog.errors and len(dialog.files)==3
        assert all(Path(path).suffix==suffix for path in dialog.files)
        assert {Path(path).parent for path in dialog.files}=={path.parent for path in photos}
        for path in dialog.files:
            with Image.open(path) as image:
                assert image.size==(160,128) and not image.getexif()
                # The template mark is composited, not merely recorded in the plan.
                pixel=image.convert('RGB').getpixel((10,11))
                assert pixel[0]>150 and pixel[1]>150
        dialog.accept()
    finally:w.close()
