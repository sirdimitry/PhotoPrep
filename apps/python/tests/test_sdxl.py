"""Small synthetic fixtures verify the optional heavy backend without downloading weights."""
from dataclasses import replace
from io import BytesIO
import hashlib,json,os
from pathlib import Path
import numpy as np
import pytest
from PySide6.QtCore import QSettings
from PIL import Image

from photoprep.catalog import MODELS,get_model
from photoprep import sdxl_store
from photoprep import inference
from photoprep.editing import PhotoEdits,MaskStroke,render_mask
from photoprep.models import Photo
from photoprep.workspace import Workspace
from photoprep.session import save_session,load_session
from photoprep.settings import Preferences
from photoprep.ui.preferences_dialog import PreferencesDialog


def fixture_spec():
    data={'model_index.json':b'{"model":"test"}','unet/test.safetensors':b'verified-weight-data'}
    spec=replace(get_model('sdxl'),files=tuple((name,len(value),hashlib.sha256(value).hexdigest()) for name,value in data.items()),size=sum(map(len,data.values())))
    return spec,data


def test_sdxl_manifest_pins_fp16_files_and_exact_size():
    spec=get_model('sdxl')
    assert spec.size==6941218469 and len(spec.files)==18 and len(spec.revision)==40
    assert sum(name.endswith('.fp16.safetensors') for name,_,_ in spec.files)==4
    assert all(len(sha)==64 and '..' not in Path(name).parts for name,_,sha in spec.files)


def test_multifile_download_verifies_all_before_commit_and_preserves_old(tmp_path,monkeypatch):
    spec,data=fixture_spec();root=tmp_path/spec.filename
    class Response(BytesIO):url='https://huggingface.co/model'
    calls=[]
    def fetch(request,**kwargs):
        assert spec.revision in request.full_url and not request.has_header('Authorization')
        name=request.full_url.split(spec.revision+'/')[1].split('?',1)[0];calls.append(name)
        return Response(data[name])
    monkeypatch.setattr(sdxl_store.urllib.request,'urlopen',fetch)
    import certifi
    sdxl_store.download(root,spec,lambda *args:None,certifi)
    assert sdxl_store.present(root,spec) and sdxl_store.verified(root,spec)
    assert sdxl_store.disk_bytes(root,spec)==spec.size
    old={name:(root/name).read_bytes() for name in data}
    monkeypatch.setattr(sdxl_store.urllib.request,'urlopen',lambda request,**kwargs:Response(b'X'*len(data[request.full_url.split(spec.revision+'/')[1].split('?',1)[0]])))
    with pytest.raises(ValueError,match='model_integrity_error'):sdxl_store.download(root,spec,lambda *args:None,certifi)
    assert {name:(root/name).read_bytes() for name in data}==old
    assert not list(tmp_path.glob('*.part'))


def test_multifile_symlinks_are_rejected_and_delete_keeps_unrelated_files(tmp_path):
    spec,data=fixture_spec();root=tmp_path/'model';root.mkdir()
    for name,value in data.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
    (root/'keep.txt').write_text('user file')
    target=root/'unet/test.safetensors';target.unlink();target.symlink_to(root/'keep.txt')
    assert not sdxl_store.verified(root,spec)
    with pytest.raises(ValueError):sdxl_store.delete(root,spec)
    assert (root/'keep.txt').read_text()=='user file'
    target.unlink();target.write_bytes(data['unet/test.safetensors'])
    sdxl_store.delete(root,spec);assert (root/'keep.txt').exists()


def test_cancel_multifile_download_cleans_only_own_partial(tmp_path):
    root=tmp_path/'model';own=root.with_name(root.name+'.12345.part');other=root.with_name(root.name+'.99999.part')
    own.mkdir();other.mkdir();(own/'weights').write_bytes(b'partial');(other/'weights').write_bytes(b'other')
    inference.cleanup_download(root,12345)
    assert not own.exists() and (other/'weights').read_bytes()==b'other'


def test_sdxl_1024_compositor_preserves_unmasked_rgba_and_colour():
    data=np.full((250,400,4),[30,80,130,210],dtype=np.uint8)
    source=inference.array_image(data);mask=render_mask(400,250,(MaskStroke(((.3,.4),),.12),))
    class Predict:
        resolution=1024
        def __call__(self,image,mask):
            assert image.shape==(1,3,1024,1024) and mask.shape==(1,1,1024,1024)
            return np.full_like(image,240)
    result=inference.image_array(inference.inpaint(source,mask,Predict()));coverage=inference.mask_array(mask)
    assert np.array_equal(result[coverage==0],data[coverage==0]) and np.array_equal(result[:,:,3],data[:,:,3])
    assert np.all(result[coverage==255,:3]==240)


def test_sdxl_passes_are_saved_in_new_session_version(tmp_path):
    source=tmp_path/'source.png';Image.new('RGB',(320,200),'blue').save(source)
    w=Workspace();w.add([Photo.from_path(source)]);stroke=MaskStroke(((.3,.4),),.1)
    w.set_edits(source,PhotoEdits(passes=((stroke,),),pass_models=('sdxl',)))
    path=tmp_path/'set.photoprep.json';save_session(path,w)
    assert json.loads(path.read_text())['version']==7
    restored,_=load_session(path);assert restored.edits[source].models_for_passes==('sdxl',)


def test_sdxl_advice_visible_before_download_in_both_languages(tmp_path,qt_application_lifetime):
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat));prefs.language='ru'
    d=PreferencesDialog(prefs)
    try:
        text=d.models.cards['sdxl']['description'].text()
        assert '6,94' in text and 'медленнее' in text and 'LaMa/MI-GAN' in text
        d.language_buttons['en'].click();text=d.models.cards['sdxl']['description'].text()
        assert '6.94' in text and 'slower' in text
        assert prefs.model_id=='lama'
    finally:d.reject()


def test_interrupted_sdxl_file_resumes_without_losing_installed_data(tmp_path,monkeypatch):
    import urllib.error
    spec,data=fixture_spec();name=next(iter(data));content=data[name]
    spec=replace(spec,files=((name,len(content),hashlib.sha256(content).hexdigest()),),size=len(content))
    class Interrupted(BytesIO):
        url='https://huggingface.co/model';status=200
        def read(self,size=-1):
            if self.tell():raise urllib.error.URLError('connection reset')
            return super().read(4)
    class Resumed(BytesIO):
        url='https://huggingface.co/model';status=206;headers={'Content-Range':f'bytes 4-{len(content)-1}/{len(content)}'}
    calls=[]
    def fetch(request,**kwargs):
        calls.append(request)
        if len(calls)==1:return Interrupted(content)
        assert request.get_header('Range')=='bytes=4-'
        return Resumed(content[4:])
    monkeypatch.setattr(sdxl_store.urllib.request,'urlopen',fetch);monkeypatch.setattr(sdxl_store.time,'sleep',lambda seconds:None)
    import certifi
    root=tmp_path/'model';sdxl_store.download(root,spec,lambda *args:None,certifi)
    assert sdxl_store.verified(root,spec) and len(calls)==2


def test_download_button_only_forces_explicit_reinstall(tmp_path,monkeypatch,qt_application_lifetime):
    import sys,time
    from PySide6.QtCore import QProcess
    from PySide6.QtTest import QTest
    import photoprep.ui.model_manager as module
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    requests=[]
    class Recorder(QProcess):
        def start(self):
            requests.append(json.loads(Path(self.arguments()[-1]).read_text()))
            self.setProgram(sys.executable);self.setArguments(['-c','print("{}")']);super().start()
    monkeypatch.setattr(module,'QProcess',Recorder);monkeypatch.setattr(module,'storage_root',lambda:tmp_path)
    manager=module.ModelManager(prefs)
    try:
        for state,expected in (('absent',False),('ready',True)):
            manager._states={'sdxl':{'state':state,'bytes':0}}
            manager.run('download','sdxl')
            end=time.monotonic()+10
            while manager.busy and time.monotonic()<end:QTest.qWait(10)
            assert not manager.busy and requests[-1]['force'] is expected
    finally:manager.shutdown();manager.close()
