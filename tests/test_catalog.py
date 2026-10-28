from dataclasses import replace
from io import BytesIO
from pathlib import Path
import hashlib,json,time

import pytest
from PySide6.QtCore import QSettings,QProcess
from PySide6.QtGui import QImage,QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialogButtonBox

from photoprep.catalog import MODELS,get_model
from photoprep.editing import PhotoEdits,MaskStroke
from photoprep.settings import Preferences
from photoprep.session import save_session,load_session,SessionError
from photoprep.ui.preferences_dialog import PreferencesDialog
from photoprep.ui.main_window import MainWindow
import photoprep.inference as inference


def app():
    result=QApplication.instance() or QApplication([])
    result.setQuitOnLastWindowClosed(False)
    return result


def wait(predicate):
    end=time.monotonic()+8
    while not predicate() and time.monotonic()<end:QTest.qWait(10)
    assert predicate()


def preferences(tmp_path):
    return Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))


def test_model_choice_is_saved_only_on_apply(tmp_path):
    application=app();prefs=preferences(tmp_path)
    d=PreferencesDialog(prefs)
    d.models.cards['migan']['choice'].setChecked(True)
    d.reject();assert prefs.model_id=='lama'
    d=PreferencesDialog(prefs)
    d.models.cards['migan']['choice'].setChecked(True)
    d.apply_and_close();assert prefs.model_id=='migan'
    prefs._q.setValue('ai/model',['bad'])
    assert prefs.model_id=='lama'
    with pytest.raises(ValueError,match='unknown_model'):prefs.model_id='unknown'


def test_force_reinstall_failure_preserves_valid_model(tmp_path,monkeypatch):
    application=app();data=b'a small model for local test'
    spec=replace(MODELS['migan'],size=len(data),sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(MODELS,'migan',spec)
    target=tmp_path/spec.filename;target.write_bytes(data)
    class Response(BytesIO):url='https://model.example/file'
    monkeypatch.setattr(inference.urllib.request,'urlopen',lambda *args,**kwargs:Response(b'X'*len(data)))
    with pytest.raises(ValueError,match='model_integrity_error'):
        inference.download_model(target,'migan',force=True)
    assert inference.model_verified(target,'migan')
    assert not list(tmp_path.glob('*.part'))


def test_download_lock_and_cleanup_do_not_touch_another_process(tmp_path,monkeypatch):
    application=app();target=tmp_path/get_model('migan').filename
    other=target.with_name(target.name+'.999999.part');other.write_bytes(b'other download')
    own=target.with_name(target.name+'.123456.part');own.write_bytes(b'own download')
    with inference.model_lock(target):
        with pytest.raises(ValueError,match='model_busy'):
            inference.download_model(target,'migan',force=True)
    inference.cleanup_download(target,123456)
    assert not own.exists() and other.read_bytes()==b'other download'


def test_model_tab_inspects_files_and_retranslates_without_changing_selection(tmp_path):
    application=app();prefs=preferences(tmp_path)
    d=PreferencesDialog(prefs);d.tabs.setCurrentIndex(1);d.show()
    wait(lambda:bool(d.models._states) and not d.models.busy)
    assert set(d.models._states)==set(MODELS)
    for language in ('ru','en'):
        d.language_buttons[language].setChecked(True)
        for card in d.models.cards.values():
            assert card['download'].text() not in ('','model_download')
            assert card['download'].geometry().right()<card['verify'].geometry().left()
            assert card['verify'].geometry().right()<card['delete'].geometry().left()
    assert d.models.selected_model=='lama'
    assert d.height()<700
    d.reject()


def test_model_cancel_preserves_old_file_and_only_cleans_own_partial(tmp_path,monkeypatch):
    application=app();from photoprep.ui import model_manager as module
    monkeypatch.setattr(module,'storage_root',lambda:tmp_path)
    target=tmp_path/'migan.onnx';target.write_bytes(b'installed model')
    monkeypatch.setattr(module,'model_path',lambda *args:target)
    class SlowProcess(QProcess):
        def start(self):
            import sys
            self.setProgram(sys.executable);self.setArguments(['-c','import time;time.sleep(30)'])
            super().start()
    monkeypatch.setattr(module,'QProcess',SlowProcess)
    d=PreferencesDialog(preferences(tmp_path))
    d.models.run('download','migan')
    wait(lambda:d.models._pid>0)
    assert not d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    own=target.with_name(target.name+f'.{d.models._pid}.part');own.write_bytes(b'partial')
    other=target.with_name(target.name+'.999999.part');other.write_bytes(b'other')
    d.models.cancel();wait(lambda:not d.models.busy)
    assert target.read_bytes()==b'installed model'
    assert not own.exists() and other.exists()
    assert d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert not list((tmp_path/'work/model-jobs').glob('catalog-*'))
    d.reject()


def test_mixed_models_keep_recipe_identity_and_restore_original_models(tmp_path,monkeypatch):
    application=app();prefs=preferences(tmp_path)
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=tmp_path/'source.png'
    image=QImage(400,300,QImage.Format.Format_RGBA8888);image.fill(QColor('blue'));image.save(str(source))
    w=MainWindow();w._confirm_discard=lambda:True;w.show();w.import_paths([str(source)]);wait(lambda:not w.canvas.loading)
    try:
        a,b=MaskStroke(((.2,.2),),.1),MaskStroke(((.7,.7),),.1)
        edits=PhotoEdits((b,),None,((a,),),('lama',))
        w.workspace.set_edits(source,edits);w.canvas.set_edits(edits)
        w._previews[w._preview_key()]=image
        key=w._preview_key();prefs.model_id='migan'
        assert w._preview_key()==key and w._current_preview()==image
        requests=[];monkeypatch.setattr(w.ai,'start',lambda *args,**kwargs:requests.append((args,kwargs)))
        w._process_mask();args,kwargs=requests.pop()
        assert kwargs['model_id']=='migan' and kwargs['base_image']==image
        w._ai_completed(args[2],image)
        assert w.workspace.edits[source].models_for_passes==('lama','migan')
        session=tmp_path/'mixed.photoprep.json';save_session(session,w.workspace)
        assert json.loads(session.read_text())['version']==4
        restored,_=load_session(session)
        assert restored.edits[source].models_for_passes==('lama','migan')
        w.workspace=restored;w._previews.clear();w._present_workspace();wait(lambda:not w.canvas.loading)
        prefs.model_id='lama';w._process_mask();args,kwargs=requests.pop()
        assert kwargs['replay_models']==('lama','migan') and kwargs['base_image'] is None
    finally:
        w.ai.shutdown();w.canvas.clear_photo();w.canvas._pool.waitForDone(5000);w.close()


@pytest.mark.parametrize('models',[['bad'],['lama','migan'],42])
def test_invalid_recipe_model_identifiers_are_rejected(tmp_path,models):
    application=app();source=tmp_path/'source.png'
    image=QImage(40,30,QImage.Format.Format_RGB32);image.fill(QColor('blue'));image.save(str(source))
    path=tmp_path/'invalid.photoprep.json'
    path.write_text(json.dumps({'format':'PhotoPrep','version':4,'photos':[{'path':source.name,'edits':{'passes':[[{'points':[[.5,.5]],'width':.1}]],'pass_models':models}}]}))
    with pytest.raises(SessionError):load_session(path)
