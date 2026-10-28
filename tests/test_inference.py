import hashlib
from io import BytesIO
from pathlib import Path
import time

import numpy as np
import pytest
from PySide6.QtCore import QSettings, QProcess, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import photoprep.inference as ai
from photoprep.editing import MaskStroke, PhotoEdits, render_mask
from photoprep.settings import Preferences
from photoprep.ui.ai_controller import AIController
from photoprep.ui.main_window import MainWindow


def test_composite_preserves_unmasked_pixels_and_alpha():
    original=np.zeros((321,617,4),dtype=np.uint8)
    original[:]=[30,80,130,210]
    image=ai.array_image(original)
    mask=render_mask(617,321,(MaskStroke(((.25,.3),(.4,.3)),.1),))
    def predict(image,mask):
        assert image.shape==(1,3,512,512) and mask.shape==(1,1,512,512)
        assert image.dtype==np.float32 and mask.dtype==np.float32
        assert 0<=image.min()<=image.max()<=1
        return np.full_like(image,240)
    result=ai.image_array(ai.inpaint(image,mask,predict))
    coverage=ai.mask_array(mask)
    assert np.array_equal(result[coverage==0],original[coverage==0])
    assert np.array_equal(result[:,:,3],original[:,:,3])
    assert np.any(result[coverage>0,:3]!=original[coverage>0,:3])
    assert np.all(result[coverage==255,:3]==240)


def test_empty_mask_and_bad_model_output_are_rejected():
    source=QImage(31,50,QImage.Format.Format_RGBA8888)
    source.fill(Qt.GlobalColor.red)
    mask=render_mask(31,50,())
    with pytest.raises(ValueError,match='empty_mask'):
        ai.inpaint(source,mask,lambda *args:None)
    mask.fill(255)
    with pytest.raises(ValueError,match='inference_output_error'):
        ai.inpaint(source,mask,lambda *args:np.full((1,3,512,512),np.nan))
    with pytest.raises(ValueError,match='inference_output_error'):
        ai.inpaint(source,mask,lambda *args:np.zeros((1,3,100,100)))


def test_model_download_is_pinned_atomic_and_verified(tmp_path,monkeypatch):
    data=b'verified test model bytes'
    from dataclasses import replace
    from photoprep.catalog import MODELS
    monkeypatch.setitem(MODELS,'lama',replace(MODELS['lama'],size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    target=tmp_path/'model.onnx'
    class Response(BytesIO):
        url='https://public-model.example/file'
    requests=[]
    def download(request,**kwargs):
        requests.append(request)
        assert request.full_url==ai.MODEL_URL
        assert ai.MODEL_REVISION in request.full_url
        assert not request.has_header('Authorization')
        return Response(data)
    monkeypatch.setattr(ai.urllib.request,'urlopen',download)
    ai.download_model(target)
    assert ai.model_verified(target)
    assert not target.with_suffix('.onnx.part').exists()
    ai.download_model(target)
    assert len(requests)==1
    target.write_bytes(b'bad data')
    monkeypatch.setattr(ai.urllib.request,'urlopen',lambda *args,**kwargs:Response(b'x'*len(data)))
    with pytest.raises(ValueError,match='model_integrity_error'):
        ai.download_model(target)
    assert target.read_bytes()==b'bad data'
    assert not target.with_suffix('.onnx.part').exists()


def test_context_clamps_to_image_and_contains_edge_masks():
    for point in ((0,0),(1,1),(.5,.5)):
        mask=render_mask(270,100,(MaskStroke((point,),.2),))
        coverage=ai.mask_array(mask)
        x,y,w,h=ai.context_rect(coverage)
        assert 0<=x<x+w<=270 and 0<=y<y+h<=100
        assert np.count_nonzero(coverage[y:y+h,x:x+w])==np.count_nonzero(coverage)


def test_cancel_child_process_cleans_temporary_private_files(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    import photoprep.ui.ai_controller as module
    monkeypatch.setattr(module,'storage_root',lambda:tmp_path)
    monkeypatch.setattr(module,'model_path',lambda *args:tmp_path/'model.onnx')
    class SlowProcess(QProcess):
        def start(self):
            import sys
            self.setProgram(sys.executable)
            self.setArguments(['-c','import time;time.sleep(30)'])
            super().start()
    monkeypatch.setattr(module,'QProcess',SlowProcess)
    controller=AIController()
    errors=[];completed=[]
    controller.failed.connect(errors.append)
    controller.completed.connect(lambda *args:completed.append(args))
    source=tmp_path/'source.png'
    image=QImage(40,30,QImage.Format.Format_RGB32);image.fill(Qt.GlobalColor.red)
    image.save(str(source))
    controller.start(source,render_mask(40,30,(MaskStroke(((.5,.5),),.2),)),('context',))
    directory=controller._directory
    assert directory.is_dir() and (directory/'mask.png').exists()
    QTest.qWait(50)
    partial=tmp_path/f"model.onnx.{controller._child_pid}.part"
    partial.write_bytes(b"incomplete download")
    controller.cancel()
    end=time.monotonic()+5
    while controller.busy and time.monotonic()<end:QTest.qWait(10)
    assert not controller.busy
    assert not directory.exists()
    assert not partial.exists()
    assert not errors and not completed
    assert source.exists()


def test_preview_comparison_refinement_and_source_integrity(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=tmp_path/'source.png'
    original=QImage(400,300,QImage.Format.Format_RGBA8888);original.fill(Qt.GlobalColor.blue)
    original.save(str(source))
    digest=hashlib.sha256(source.read_bytes()).digest()
    window=MainWindow();window._confirm_discard=lambda:True
    window.show()
    app.processEvents()
    try:
        window.import_paths([str(source)])
        end=time.monotonic()+5
        while window.canvas.loading and time.monotonic()<end:QTest.qWait(10)
        key=window._job_key()
        processed=original.copy();processed.fill(Qt.GlobalColor.green)
        window._ai_completed(key,processed)
        window._refresh_controls()
        assert window.canvas._preview_active and window.tools['compare'].isChecked()
        assert window.tools['compare'].isEnabled()
        view=window.canvas.view_state()
        window.tools['compare'].click()
        assert not window.canvas._preview_active
        assert window.canvas._pixmap_item.pixmap().toImage().pixelColor(1,1)==original.pixelColor(1,1)
        window.tools['compare'].click()
        assert window.canvas._preview_active
        assert window.canvas.view_state()==view
        window._select_tool('mask')
        assert window.canvas._preview_active and window.tools['compare'].isChecked()
        assert window.canvas._mask_overlay.isVisible()
        edits=PhotoEdits((MaskStroke(((.5,.5),),.1),))
        window._edits_committed(source.resolve(),edits)
        assert window._current_preview() is not None
        assert window.tools['compare'].isEnabled()
        window._ai_completed(key,processed)
        assert window.canvas._preview_active  # stale completion cannot replace a newer mask
        assert window.workspace.edits[source.resolve()]==edits
        assert hashlib.sha256(source.read_bytes()).digest()==digest
        for lang in ('en','ru'):
            prefs.language=lang;window.retranslate()
            assert window.process_button.text() not in ('process_mask','')
    finally:
        window.ai.shutdown()
        window.canvas.clear_photo();window.canvas._pool.waitForDone(5000)
        window.close();app.processEvents()
