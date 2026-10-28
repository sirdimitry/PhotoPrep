from dataclasses import replace
from pathlib import Path
import hashlib
import json
import time

import pytest
from PySide6.QtCore import QSettings,Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from photoprep.editing import MaskStroke,PhotoEdits
from photoprep.models import Photo
from photoprep.session import load_session,save_session,SessionError
from photoprep.settings import Preferences
from photoprep.ui.main_window import MainWindow


def wait_for(predicate):
    end=time.monotonic()+5
    while not predicate() and time.monotonic()<end:QTest.qWait(10)
    assert predicate()


@pytest.fixture
def window(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=tmp_path/'original.png'
    image=QImage(400,300,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.blue)
    image.save(str(source))
    window=MainWindow();window._confirm_discard=lambda:True
    window.show();app.processEvents();window.import_paths([str(source)])
    wait_for(lambda:not window.canvas.loading)
    yield window,source,image
    window.ai.shutdown();window.canvas.clear_photo();window.canvas._pool.waitForDone(5000)
    window.close();app.processEvents()


def stroke_at(x,y):
    return MaskStroke(((x,y),),.1)


def commit_mask(window,strokes):
    edits=replace(window.workspace.edits[window.workspace.selected],strokes=strokes)
    window.canvas.set_edits(edits)
    window._edits_committed(window.workspace.selected,edits)


def test_passes_use_previous_result_and_undo_redo_atomically(window,monkeypatch):
    w,source,original=window
    original_hash=hashlib.sha256(source.read_bytes()).digest()
    requests=[]
    monkeypatch.setattr(w.ai,'start',lambda *args,**kwargs:requests.append((args,kwargs)))
    a,b=stroke_at(.2,.2),stroke_at(.7,.7)
    w._select_tool('mask');commit_mask(w,(a,));w._process_mask()
    args,kwargs=requests.pop()
    assert kwargs['base_image'] is None and kwargs['replay']==()
    first=original.copy();first.setPixelColor(80,60,Qt.GlobalColor.red)
    w._ai_completed(args[2],first)
    assert w.workspace.edits[source].passes==((a,),)
    assert not w.workspace.edits[source].strokes
    assert w.canvas.tool=='mask' and w.canvas._preview_active
    assert w.canvas._mask_overlay.isVisible()
    commit_mask(w,(b,))
    assert w._current_preview()==first
    w._process_mask()
    args,kwargs=requests.pop()
    assert kwargs['base_image']==first
    assert kwargs['replay']==()
    second=first.copy();second.setPixelColor(280,210,Qt.GlobalColor.green)
    w._ai_completed(args[2],second)
    assert w.workspace.edits[source].passes==((a,),(b,))
    assert not w.workspace.edits[source].strokes
    assert w._current_preview().pixelColor(80,60)==first.pixelColor(80,60)
    assert w._current_preview().pixelColor(280,210)==second.pixelColor(280,210)
    w.tools['compare'].click()
    assert w.canvas._pixmap_item.pixmap().toImage().pixelColor(80,60)==original.pixelColor(80,60)
    w.tools['compare'].click()
    assert w.canvas._preview_active
    w.undo();wait_for(lambda:not w.canvas.loading)
    assert w.workspace.edits[source].passes==((a,),)
    assert w.workspace.edits[source].strokes==(b,)
    assert w._current_preview()==first
    w.redo();wait_for(lambda:not w.canvas.loading)
    assert w.workspace.edits[source].passes==((a,),(b,))
    assert w._current_preview()==second
    assert hashlib.sha256(source.read_bytes()).digest()==original_hash


def test_restoration_replays_saved_passes_without_duplicating_them(window,monkeypatch,tmp_path):
    w,source,original=window
    a,b=stroke_at(.2,.2),stroke_at(.7,.7)
    edits=PhotoEdits((),None,((a,),(b,)))
    w.workspace.set_edits(source,edits)
    session=tmp_path/'saved.photoprep.json';save_session(session,w.workspace)
    assert json.loads(session.read_text())['version']==3
    restored,_=load_session(session)
    assert restored.edits[source]==edits
    w.workspace=restored;w._previews.clear();w._present_workspace()
    wait_for(lambda:not w.canvas.loading)
    assert w.process_button.isEnabled() and w._current_preview() is None
    requests=[]
    monkeypatch.setattr(w.ai,'start',lambda *args,**kwargs:requests.append((args,kwargs)))
    w._process_mask()
    args,kwargs=requests.pop()
    assert args[1] is None and kwargs['base_image'] is None
    assert kwargs['replay']==edits.passes
    w._ai_completed(args[2],original)
    assert w.workspace.edits[source]==edits
    assert not w.workspace.dirty
    assert w._current_preview() is not None


def test_cancel_and_failure_do_not_consume_pending_mask_or_previous_pass(window,monkeypatch):
    w,source,image=window
    a,b=stroke_at(.2,.2),stroke_at(.7,.7)
    w.workspace.set_edits(source,PhotoEdits((),None,((a,),)))
    w._previews[w._preview_key()]=image
    w.canvas.set_edits(w.workspace.edits[source]);w._select_tool('mask')
    commit_mask(w,(b,));before=w.workspace.snapshot()
    monkeypatch.setattr(w.ai,'start',lambda *args,**kwargs:None)
    monkeypatch.setattr('photoprep.ui.main_window.QMessageBox.warning',lambda *args:None)
    w._process_mask();w._cancel_ai();w._refresh_controls()
    assert w.workspace.snapshot()==before and w._current_preview()==image
    w._ai_failed('inference_error')
    assert w.workspace.snapshot()==before and w._current_preview()==image
    w.canvas.clear_mask()
    assert w.workspace.edits[source].passes==((a,),)
    assert w._current_preview()==image


def test_controller_stages_previous_pixels_and_replay_privately(tmp_path,monkeypatch):
    from photoprep.ui import ai_controller as module
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(module,'storage_root',lambda:tmp_path)
    monkeypatch.setattr(module,'model_path',lambda *args:tmp_path/'model.onnx')
    controller=module.AIController()
    monkeypatch.setattr(controller,'_launch',lambda *args:None)
    image=QImage(40,30,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.green)
    controller.start(tmp_path/'original.png',image,('context',),base_image=image)
    directory=controller._directory
    request=json.loads((directory/'request.json').read_text())
    assert Path(request['source']).parent==directory
    assert QImage(request['source']).convertToFormat(QImage.Format.Format_RGBA8888)==image
    assert request['replay']==[]
    controller.shutdown()
    assert not directory.exists()


@pytest.mark.parametrize('passes',[{},[[]],[{'bad':'mask'}],[[]]*101])
def test_malformed_pass_recipes_are_rejected(tmp_path,passes):
    source=tmp_path/'source.png'
    image=QImage(40,30,QImage.Format.Format_RGB32);image.fill(Qt.GlobalColor.red);image.save(str(source))
    session=tmp_path/'bad.photoprep.json'
    session.write_text(json.dumps({'format':'PhotoPrep','version':3,'photos':[{'path':source.name,'edits':{'passes':passes}}]}))
    with pytest.raises(SessionError):load_session(session)
