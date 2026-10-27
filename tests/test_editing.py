import hashlib
import json
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from photoprep.editing import MaskStroke, PhotoEdits, CropRect, fit_crop, render_mask
from photoprep.models import Photo
from photoprep.session import load_session, save_session, SessionError
from photoprep.settings import Preferences
from photoprep.workspace import Workspace
from photoprep.ui.main_window import MainWindow


def wait_for(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end:
        QTest.qWait(10)
    assert predicate()


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    window=MainWindow()
    window._confirm_discard=lambda:True
    window.show()
    app.processEvents()
    yield window
    window.canvas.clear_photo()
    window.canvas._pool.waitForDone(5000)
    window.close()
    app.processEvents()


@pytest.fixture
def photo(tmp_path):
    path=tmp_path/'original.png'
    Image.new('RGB',(400,300),'#4488CC').save(path)
    return Photo.from_path(path)


def drag(canvas,start,end):
    viewport=canvas.viewport()
    a,b=canvas.mapFromScene(QPointF(*start)),canvas.mapFromScene(QPointF(*end))
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,pos=a)
    for i in range(1,6):
        QTest.mouseMove(viewport,a+(b-a)*i/5)
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,pos=b)
    QApplication.processEvents()


def test_full_resolution_mask_and_eraser_are_precise():
    brush=MaskStroke(((.2,.5),(.8,.5)),.2)
    erase=MaskStroke(((.5,.5),),.1,True)
    mask=render_mask(200,100,(brush,erase))
    assert mask.size().width()==200 and mask.size().height()==100
    assert mask.pixelColor(40,50).red()==255
    assert mask.pixelColor(100,50).red()==0
    assert mask.pixelColor(100,10).red()==0
    assert mask.pixelColor(160,50).red()==255


def test_crop_fits_portrait_and_landscape():
    for width,height in ((400,300),(300,500),(1,1)):
        crop=fit_crop(width,height,1136/710)
        rect=crop.pixels(width,height)
        assert rect.width()/rect.height()==pytest.approx(1136/710)
        assert 0<=crop.x<=1 and 0<=crop.y<=1
        assert crop.x+crop.width<=1.000001 and crop.y+crop.height<=1.000001


def test_edit_history_and_output_ratio_are_atomic(photo):
    workspace=Workspace()
    workspace.add([photo])
    edits=PhotoEdits((MaskStroke(((.5,.5),),.1),),fit_crop(400,300,1.6))
    assert workspace.set_edits(photo.path,edits)
    assert workspace.set_output_size(1000,1000)
    changed=workspace.edits[photo.path].crop.pixels(400,300)
    assert changed.width()/changed.height()==pytest.approx(1)
    assert workspace.undo()
    assert workspace.edits[photo.path]==edits
    assert (workspace.output_width,workspace.output_height)==(1136,710)
    assert workspace.undo()
    assert workspace.edits[photo.path]==PhotoEdits()
    assert workspace.redo()
    assert workspace.edits[photo.path]==edits


def test_mask_crop_session_roundtrip_and_legacy(photo,tmp_path):
    workspace=Workspace(output_width=1600,output_height=1000)
    workspace.add([photo])
    workspace.set_edits(photo.path,PhotoEdits((MaskStroke(((.2,.3),(.4,.5)),.1),),fit_crop(400,300,1.6)))
    path=tmp_path/'edit.photoprep.json'
    save_session(path,workspace)
    restored,skipped=load_session(path)
    assert skipped==0
    assert restored.edits[photo.path].strokes==workspace.edits[photo.path].strokes
    assert restored.edits[photo.path].crop.width==pytest.approx(workspace.edits[photo.path].crop.width)
    assert restored.output_width==1600 and restored.output_height==1000
    assert not restored.dirty
    path.write_text(json.dumps({'format':'PhotoPrep','version':1,'photos':[{'path':photo.path.name}]}))
    legacy,_=load_session(path)
    assert legacy.edits[photo.path]==PhotoEdits()
    assert (legacy.output_width,legacy.output_height)==(1136,710)


@pytest.mark.parametrize('edits',[
    {'strokes':[{'points':[[float('nan'),.5]],'width':.1}]},
    {'strokes':[{'points':[[.5,.5]],'width':float('inf')}]},
    {'strokes':[], 'crop':{'x':.9,'y':0,'width':.5,'height':1}},
])
def test_invalid_edit_geometry_is_rejected(photo,tmp_path,edits):
    path=tmp_path/'invalid.photoprep.json'
    path.write_text(json.dumps({'format':'PhotoPrep','version':2,'photos':[{'path':photo.path.name,'edits':edits}]}))
    with pytest.raises(SessionError):
        load_session(path)


def test_brush_eraser_undo_and_source_integrity(window,photo):
    digest=hashlib.sha256(photo.path.read_bytes()).hexdigest()
    window.import_paths([str(photo.path)])
    wait_for(lambda:not window.canvas.loading)
    window._select_tool('mask')
    window.brush_slider.setValue(40)
    drag(window.canvas,(100,150),(300,150))
    edits=window.workspace.edits[photo.path]
    assert len(edits.strokes)==1
    assert render_mask(400,300,edits.strokes).pixelColor(200,150).red()==255
    window._select_tool('erase')
    drag(window.canvas,(200,140),(200,160))
    assert len(window.workspace.edits[photo.path].strokes)==2
    assert render_mask(400,300,window.workspace.edits[photo.path].strokes).pixelColor(200,150).red()==0
    window.undo()
    wait_for(lambda:not window.canvas.loading)
    assert len(window.workspace.edits[photo.path].strokes)==1
    window.canvas.clear_mask()
    assert not window.workspace.edits[photo.path].strokes
    window.undo()
    wait_for(lambda:not window.canvas.loading)
    assert len(window.workspace.edits[photo.path].strokes)==1
    assert hashlib.sha256(photo.path.read_bytes()).hexdigest()==digest


def test_drag_crop_keeps_ratio_and_is_undoable(window,photo):
    window.import_paths([str(photo.path)])
    wait_for(lambda:not window.canvas.loading)
    window._select_tool('crop')
    rect=window.canvas._crop_overlay.crop.pixels(400,300)
    drag(window.canvas,(rect.right(),rect.bottom()),(rect.right()-90,rect.bottom()-60))
    crop=window.workspace.edits[photo.path].crop
    assert crop is not None
    assert crop.width<1
    assert crop.pixels(400,300).width()/crop.pixels(400,300).height()==pytest.approx(1136/710)
    center=crop.pixels(400,300).center()
    drag(window.canvas,(center.x(),center.y()),(center.x()+1000,center.y()+1000))
    moved=window.workspace.edits[photo.path].crop
    assert moved.x+moved.width<=1.000001 and moved.y+moved.height<=1.000001
    window.undo()
    wait_for(lambda:not window.canvas.loading)
    assert window.workspace.edits[photo.path].crop==crop
    window.canvas.clear_crop()
    assert window.workspace.edits[photo.path].crop is None
    window.undo()
    wait_for(lambda:not window.canvas.loading)
    assert window.workspace.edits[photo.path].crop==crop


def test_settings_size_change_adapts_crop_and_undo_restores(window,photo):
    window.import_paths([str(photo.path)])
    wait_for(lambda:not window.canvas.loading)
    window._select_tool('crop')
    window.canvas.reset_crop()
    window.settings.output_width=1080
    window.settings.output_height=1920
    window._preferences_applied()
    crop=window.workspace.edits[photo.path].crop.pixels(400,300)
    assert crop.width()/crop.height()==pytest.approx(1080/1920)
    assert window.export_value.text()=='1080 × 1920 px'
    window.undo()
    wait_for(lambda:not window.canvas.loading)
    assert window.export_value.text()=='1136 × 710 px'


def test_mask_belongs_to_its_photo_and_space_pan_is_temporary(window,photo,tmp_path):
    second=tmp_path/'second.png'
    Image.new('RGB',(400,300),'yellow').save(second)
    window.import_paths([str(photo.path),str(second)])
    wait_for(lambda:not window.canvas.loading)
    window._select_tool('mask')
    drag(window.canvas,(100,100),(200,100))
    assert len(window.workspace.edits[photo.path].strokes)==1
    QTest.keyPress(window.canvas,Qt.Key.Key_Space)
    assert window.canvas._pan_held
    QTest.keyRelease(window.canvas,Qt.Key.Key_Space)
    assert not window.canvas._pan_held
    window.navigate(1)
    wait_for(lambda:not window.canvas.loading)
    assert window.canvas.edits==PhotoEdits()
    window.navigate(-1)
    wait_for(lambda:not window.canvas.loading)
    assert len(window.canvas.edits.strokes)==1
    window.session_path=tmp_path/'mask.photoprep.json'
    assert window.save_workspace()
    window.new_workspace()
    assert window.open_session_file(tmp_path/'mask.photoprep.json')
    wait_for(lambda:not window.canvas.loading)
    assert len(window.canvas.edits.strokes)==1
