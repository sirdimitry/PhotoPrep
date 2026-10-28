from dataclasses import replace
from pathlib import Path
import hashlib
import pytest
from photoprep.catalog import MODELS,get_model
from photoprep.model_import import local_files,install_local
from photoprep.inference import model_verified


def test_import_valid_onnx_uses_existing_bytes_and_preserves_original(tmp_path,monkeypatch,qt_application_lifetime):
    data=b'known supported ONNX fixture';source=tmp_path/'downloaded.onnx';source.write_bytes(data)
    spec=replace(get_model('migan'),size=len(data),sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(MODELS,'migan',spec)
    target=tmp_path/'app/models'/spec.filename
    install_local(source,target,spec,lambda *args:None)
    assert model_verified(target,'migan') and source.read_bytes()==data
    assert source.stat().st_ino==target.stat().st_ino
    assert not list(target.parent.glob('*.part'))


def test_incompatible_model_never_replaces_installed_weights(tmp_path,monkeypatch,qt_application_lifetime):
    data=b'known supported bytes';spec=replace(get_model('migan'),size=len(data),sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(MODELS,'migan',spec)
    target=tmp_path/spec.filename;target.write_bytes(data)
    source=tmp_path/'wrong.onnx';source.write_bytes(b'X'*len(data))
    with pytest.raises(ValueError,match='model_incompatible'):install_local(source,target,spec,lambda *args:None)
    assert target.read_bytes()==data and source.read_bytes()==b'X'*len(data)


def test_import_sdxl_snapshot_can_read_verified_cache_symlinks(tmp_path,monkeypatch,qt_application_lifetime):
    data={'model_index.json':b'known config','unet/model.fp16.safetensors':b'known safetensors fixture'}
    files=tuple((name,len(value),hashlib.sha256(value).hexdigest()) for name,value in data.items())
    spec=replace(get_model('sdxl'),size=sum(map(len,data.values())),files=files)
    monkeypatch.setitem(MODELS,'sdxl',spec)
    source=tmp_path/'snapshot';blobs=tmp_path/'blobs';blobs.mkdir();source.mkdir()
    for index,(name,value) in enumerate(data.items()):
        blob=blobs/str(index);blob.write_bytes(value)
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.symlink_to(blob)
    target=tmp_path/'app/models/sdxl'
    install_local(source,target,spec,lambda *args:None)
    assert model_verified(target,'sdxl') and all(not (target/name).is_symlink() for name in data)
    for name,value in data.items():assert (source/name).read_bytes()==value
    (source/'unet/model.fp16.safetensors').unlink()
    with pytest.raises(ValueError,match='model_incompatible'):local_files(source,spec)


def test_download_reuses_verified_sdxl_without_network(tmp_path,monkeypatch,qt_application_lifetime):
    import photoprep.inference as inference
    data=b'known SDXL data';files=(('model_index.json',len(data),hashlib.sha256(data).hexdigest()),)
    spec=replace(get_model('sdxl'),files=files,size=len(data));monkeypatch.setitem(MODELS,'sdxl',spec)
    target=tmp_path/'model';target.mkdir();(target/'model_index.json').write_bytes(data)
    monkeypatch.setattr(inference.urllib.request,'urlopen',lambda *a,**k:pytest.fail('installed model must not use network'))
    inference.download_model(target,'sdxl')
    assert model_verified(target,'sdxl')


def test_download_connects_known_local_weights_before_network(tmp_path,monkeypatch,qt_application_lifetime):
    import photoprep.inference as inference
    import photoprep.model_import as model_import
    data=b'known local ONNX';spec=replace(get_model('migan'),size=len(data),sha256=hashlib.sha256(data).hexdigest());monkeypatch.setitem(MODELS,'migan',spec)
    source=tmp_path/'downloaded.onnx';source.write_bytes(data);target=tmp_path/'app'/spec.filename
    monkeypatch.setattr(model_import,'cached_sources',lambda spec:[source])
    monkeypatch.setattr(inference.urllib.request,'urlopen',lambda *a,**k:pytest.fail('local compatible model must not use network'))
    inference.download_model(target,'migan')
    assert model_verified(target,'migan') and source.read_bytes()==data
