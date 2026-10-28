from dataclasses import replace
from pathlib import Path
import hashlib,json,time

import numpy as np
import pytest
from PIL import Image,PngImagePlugin,TiffImagePlugin
from PySide6.QtCore import QSettings,Qt,QPoint,QProcess
from PySide6.QtGui import QImage,QColor,QImageReader
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from photoprep.branding import LogoPlacement,logo_rect,read_logo
from photoprep.editing import PhotoEdits,CropRect,MaskStroke
from photoprep.exporting import compose,save_clean,signature,export_job
from photoprep.models import Photo
from photoprep.session import save_session,load_session,SessionError
from photoprep.settings import Preferences
from photoprep.workspace import Workspace
from photoprep.ui.main_window import MainWindow
from photoprep.ui.export_dialog import ExportDialog


def app():
    result=QApplication.instance() or QApplication([]);result.setQuitOnLastWindowClosed(False);return result


def wait(predicate):
    end=time.monotonic()+8
    while not predicate() and time.monotonic()<end:QTest.qWait(10)
    assert predicate()


def make_source(path,size=(320,200)):
    Image.new('RGB',size,'#224488').save(path)
    return Photo.from_path(path)


def request_for(tmp_path,workspace,format='PNG'):
    session=tmp_path/'plan.photoprep.json';save_session(session,workspace)
    data={'session':str(session),'sources':{str(p.path):signature(p.path) for p in workspace.photos},'protected':[str(p.path) for p in workspace.photos],
          'logos':{ed.logo.path:signature(ed.logo.path) for ed in workspace.edits.values() if ed.logo},'models':{},'folder':str(tmp_path/'output'),'format':format,'quality':90}
    request=tmp_path/'job.json';request.write_text(json.dumps(data));return request


def test_crop_geometry_and_logo_alpha(tmp_path):
    application=app()
    source=QImage(320,200,QImage.Format.Format_RGBA8888);source.fill(QColor('blue'))
    logo=tmp_path/'logo.png';Image.new('RGBA',(80,40),(0,255,0,128)).save(logo)
    placement=LogoPlacement(str(logo),width=.25,opacity=.5)
    edits=PhotoEdits(logo=placement)
    output=compose(source,edits,160,160)
    assert output.size().width()==160 and output.size().height()==160
    from PySide6.QtCore import QRectF
    rect=logo_rect(QRectF(0,0,160,160),placement,read_logo(logo))
    color=output.pixelColor(rect.center().toPoint())
    assert color.red()==0 and abs(color.green()-64)<=1 and abs(color.blue()-191)<=1
    assert output.pixelColor(0,0)==QColor('blue')
    # A non-centered floating crop selects the same source region as the frame.
    split=QImage(320,200,QImage.Format.Format_RGB32);split.fill(QColor('blue'))
    for x in range(160):
        for y in range(200):split.setPixelColor(x,y,QColor('red'))
    crop=compose(split,PhotoEdits(crop=CropRect(0,0,.5,1)),128,160)
    assert crop.pixelColor(64,80)==QColor('red')


@pytest.mark.parametrize('format',['PNG','JPEG'])
def test_export_strips_exif_gps_xmp_comments_and_preserves_source(tmp_path,format):
    application=app();source=tmp_path/'private.jpg'
    image=Image.new('RGB',(320,200),'#4477aa');exif=Image.Exif()
    exif[315]='PRIVATE_AUTHOR';exif[270]='PRIVATE_DESCRIPTION';exif[274]=6
    exif[34853]={1:'N',2:(TiffImagePlugin.IFDRational(55),TiffImagePlugin.IFDRational(1),TiffImagePlugin.IFDRational(0)),3:'E',4:(TiffImagePlugin.IFDRational(37),TiffImagePlugin.IFDRational(1),TiffImagePlugin.IFDRational(0))}
    image.save(source,exif=exif,xmp=b'<PRIVATE_XMP/>',comment=b'PRIVATE_COMMENT')
    before=source.read_bytes();workspace=Workspace(output_width=160,output_height=160);workspace.add([Photo.from_path(source)])
    export_job(request_for(tmp_path,workspace,format))
    output=next((tmp_path/'output').iterdir())
    with Image.open(output) as result:
        assert result.size==(160,160)
        assert not result.getexif()
        assert not any(k in result.info for k in ('exif','xmp','XML:com.adobe.xmp','comment','icc_profile'))
    assert b'PRIVATE_' not in output.read_bytes()
    assert source.read_bytes()==before


def test_atomic_export_never_overwrites_existing_files_sources_or_symlinks(tmp_path):
    application=app();image=QImage(160,160,QImage.Format.Format_RGBA8888);image.fill(QColor('green'))
    protected=tmp_path/'photo-photoprep.png';protected.write_bytes(b'original source')
    linked=tmp_path/'photo-photoprep-2.png';linked.symlink_to(protected)
    output=save_clean(image,tmp_path,'photo','PNG',90,[protected])
    assert output.name=='photo-photoprep-3.png'
    assert protected.read_bytes()==b'original source' and linked.is_symlink()
    second=save_clean(image,tmp_path,'photo','PNG',90,[protected])
    assert second.name=='photo-photoprep-4.png'
    assert not list(tmp_path.glob('.photoprep-*.tmp'))


def test_quality_and_white_jpeg_transparency(tmp_path):
    application=app();rng=np.random.default_rng(4)
    data=rng.integers(0,256,(200,320,4),dtype=np.uint8);data[:,:,3]=255
    from photoprep.inference import array_image
    image=array_image(data)
    low=save_clean(image,tmp_path,'low','JPEG',20);high=save_clean(image,tmp_path,'high','JPEG',95)
    assert high.stat().st_size>low.stat().st_size
    image.fill(QColor(0,0,0,0));white=save_clean(image,tmp_path,'transparent','JPEG',95)
    with Image.open(white) as result:assert result.getpixel((100,100))==(255,255,255)


def test_logo_session_roundtrip_is_relative_and_undo_all_is_atomic(tmp_path):
    application=app();logo=tmp_path/'logo.png';Image.new('RGBA',(80,40),'green').save(logo)
    photos=[make_source(tmp_path/f'{i}.png') for i in range(2)]
    workspace=Workspace();workspace.add(photos)
    placement=LogoPlacement(str(logo),.22,.7,.1,.9)
    workspace.set_logo_for_all(placement)
    session=tmp_path/'set.photoprep.json';save_session(session,workspace)
    document=json.loads(session.read_text());assert document['version']==5
    assert not Path(document['photos'][0]['edits']['logo']['path']).is_absolute()
    restored,_=load_session(session)
    assert restored.snapshot()==workspace.snapshot()
    workspace.undo();assert all(ed.logo is None for ed in workspace.edits.values())
    workspace.redo();assert all(ed.logo==placement for ed in workspace.edits.values())


def test_batch_duplicate_stems_and_missing_photo(tmp_path):
    application=app();photos=[make_source(tmp_path/'same.jpg'),make_source(tmp_path/'same.png'),make_source(tmp_path/'missing.png')]
    workspace=Workspace(output_width=160,output_height=160);workspace.add(photos)
    request=request_for(tmp_path,workspace);photos[-1].path.unlink()
    export_job(request)
    names={p.name for p in (tmp_path/'output').iterdir()}
    assert names=={'same-photoprep.png','same-photoprep-2.png'}


def test_logo_drag_compare_and_frame_alignment(tmp_path,monkeypatch):
    application=app();prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=tmp_path/'photo.png';make_source(source,(800,600))
    logo=tmp_path/'logo.png';Image.new('RGBA',(100,50),(0,255,0,200)).save(logo)
    w=MainWindow();w._confirm_discard=lambda:True;w.show();w.import_paths([str(source)]);wait(lambda:not w.canvas.loading)
    try:
        before=hashlib.sha256(source.read_bytes()).digest()
        w._select_tool('logo');w._apply_logo_path(logo)
        assert w.canvas._logo_overlay.isVisible() and w.after_button.isEnabled()
        old=w.workspace.edits[source].logo
        rect=w.canvas.logo_source_rect;start=w.canvas.mapFromScene(rect.center());end=start+QPoint(80,60)
        QTest.mousePress(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=start);QTest.mouseMove(w.canvas.viewport(),end);QTest.mouseRelease(w.canvas.viewport(),Qt.MouseButton.LeftButton,pos=end)
        assert w.workspace.edits[source].logo!=old
        w.undo();wait(lambda:not w.canvas.loading);assert w.workspace.edits[source].logo==old
        w.redo();wait(lambda:not w.canvas.loading)
        w.before_button.click();assert not w.canvas._logo_overlay.isVisible()
        w.after_button.click();assert w.canvas._logo_overlay.isVisible()
        w._select_tool('crop')
        from PySide6.QtCore import QRectF
        output_rect=logo_rect(QRectF(0,0,w.workspace.output_width,w.workspace.output_height),w.workspace.edits[source].logo,read_logo(logo))
        frame=w.canvas.output_frame_rect;scale=frame.width()/w.workspace.output_width
        actual=w.canvas.viewportTransform().mapRect(w.canvas.logo_source_rect)
        assert actual.left()==pytest.approx(frame.left()+output_rect.left()*scale,abs=1)
        assert actual.top()==pytest.approx(frame.top()+output_rect.top()*scale,abs=1)
        assert hashlib.sha256(source.read_bytes()).digest()==before
    finally:w.canvas.clear_photo();w.canvas._pool.waitForDone(5000);w.close()


def test_pending_mask_blocks_export_and_large_output_is_rejected(tmp_path):
    application=app();photo=make_source(tmp_path/'photo.png');workspace=Workspace();workspace.add([photo])
    workspace.set_edits(photo.path,PhotoEdits((MaskStroke(((.5,.5),),.1),)))
    d=ExportDialog(workspace,Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat)),folder=tmp_path/'output')
    assert not d.start_button.isEnabled()
    d.reject()
    image=QImage(160,160,QImage.Format.Format_RGB32)
    with pytest.raises(ValueError,match='export_size_large'):compose(image,PhotoEdits(),16000,16000)


def test_cancel_export_keeps_completed_and_removes_only_own_partial(tmp_path,monkeypatch):
    application=app();from photoprep.ui import export_dialog as module
    monkeypatch.setattr(module,'storage_root',lambda:tmp_path)
    folder=tmp_path/'output'
    class SlowProcess(QProcess):
        def start(self):
            import sys
            code="from pathlib import Path;import os,json,time;f=Path(__import__('sys').argv[1]);f.mkdir(exist_ok=True);p=f/'done.png';p.write_bytes(b'committed');(f/('.photoprep-'+str(os.getpid())+'-own.tmp')).write_bytes(b'partial');print(json.dumps({'file':str(p)}),flush=True);time.sleep(30)"
            self.setProgram(sys.executable);self.setArguments(['-c',code,str(folder)]);super().start()
    monkeypatch.setattr(module,'QProcess',SlowProcess)
    photo=make_source(tmp_path/'photo.png');workspace=Workspace();workspace.add([photo])
    d=ExportDialog(workspace,Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat)),folder=folder)
    d.start();wait(lambda:len(d.files)==1)
    other=folder/'.photoprep-999999-other.tmp';other.write_bytes(b'other process')
    d.cancel_or_close();wait(lambda:not d.busy)
    assert (folder/'done.png').read_bytes()==b'committed' and other.exists()
    assert len(list(folder.glob('.photoprep-*.tmp')))==1
    assert not list((tmp_path/'work/export-jobs').glob('export-*'))
    d.accept()


@pytest.mark.parametrize('field,value',[('width',float('nan')),('opacity',2),('enabled',1),('path',42)])
def test_invalid_logo_recipe_rejected(tmp_path,field,value):
    application=app();photo=make_source(tmp_path/'photo.png')
    logo={'path':'logo.png',field:value}
    session=tmp_path/'bad.photoprep.json';session.write_text(json.dumps({'format':'PhotoPrep','version':5,'photos':[{'path':photo.path.name,'edits':{'logo':logo}}]}))
    with pytest.raises(SessionError):load_session(session)


def test_exif_orientation_is_applied_before_crop_and_removed(tmp_path):
    application=app();source=tmp_path/'rotated.jpg'
    image=Image.new('RGB',(320,200),'blue')
    image.paste('red',(0,0,160,200));exif=Image.Exif();exif[274]=6
    image.save(source,quality=100,subsampling=0,exif=exif)
    photo=Photo.from_path(source);assert (photo.width,photo.height)==(200,320)
    workspace=Workspace(output_width=160,output_height=256);workspace.add([photo])
    export_job(request_for(tmp_path,workspace))
    with Image.open(next((tmp_path/'output').iterdir())) as result:
        assert result.getpixel((80,30))[0]>240 and result.getpixel((80,230))[2]>240
        assert not result.getexif()


def test_disk_full_aborts_without_partial_or_source_change(tmp_path,monkeypatch):
    import errno
    application=app();photo=make_source(tmp_path/'photo.png')
    image=QImage(str(photo.path));before=photo.path.read_bytes()
    def full(*args,**kwargs):raise OSError(errno.ENOSPC,'disk full')
    monkeypatch.setattr(Image.Image,'save',full)
    with pytest.raises(OSError):save_clean(image,tmp_path,'photo','PNG',90,[photo.path])
    assert photo.path.read_bytes()==before and not list(tmp_path.glob('.photoprep-*.tmp'))


def test_retouch_keeps_color_space_until_clean_export():
    application=app();from PySide6.QtGui import QColorSpace
    from photoprep.inference import inpaint
    from photoprep.editing import render_mask
    source=QImage(160,160,QImage.Format.Format_RGBA8888);source.fill(QColor('blue'))
    source.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.DisplayP3))
    mask=render_mask(160,160,(MaskStroke(((.5,.5),),.1),))
    result=inpaint(source,mask,lambda image,mask:np.full((1,3,512,512),128,dtype=np.float32))
    assert result.colorSpace()==source.colorSpace()


def test_application_and_export_dialogs_exit_cleanly_in_subprocess(tmp_path):
    import os,subprocess,sys,textwrap
    source=tmp_path/'source.png';make_source(source)
    logo=tmp_path/'logo.png';Image.new('RGBA',(80,40),'green').save(logo)
    code=r'''
import ctypes,os,sys
from pathlib import Path
if os.environ.get('PHOTOPREP_TEST_CRASH_GUARD'):
    guard=ctypes.CDLL(os.environ['PHOTOPREP_TEST_CRASH_GUARD']);guard.install_test_crash_guard()
from PySide6.QtCore import QSettings,QTimer
from photoprep.settings import Preferences
from photoprep.ui import main_window as ui
from photoprep.ui.export_dialog import ExportDialog
from photoprep.main import main
folder=Path(sys.argv[1])
prefs=Preferences(QSettings(str(folder/'prefs.ini'),QSettings.Format.IniFormat))
ui.Preferences=lambda:prefs
Original=ui.MainWindow
class ClosingWindow(Original):
    def __init__(self):
        super().__init__()
        self._confirm_discard=lambda:True
        self.canvas.photo_loaded.connect(self.ready)
    def show(self):
        super().show()
        QTimer.singleShot(0,lambda:self.import_paths([str(folder/'source.png')]))
    def ready(self,path,success):
        assert success
        self._apply_logo_path(folder/'logo.png')
        for index in range(4):
            dialog=ExportDialog(self.workspace,self.settings,self,folder=folder/'output')
            dialog.show();dialog.reject()
        dialog=ExportDialog(self.workspace,self.settings,self,folder=folder/'output')
        QTimer.singleShot(0,dialog.reject)
        dialog.exec()
        QTimer.singleShot(0,self.close)
ui.MainWindow=ClosingWindow
assert main()==0
print('LIFECYCLE_OK')
'''
    environment=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    result=subprocess.run([sys.executable,'-c',textwrap.dedent(code),str(tmp_path)],env=environment,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'LIFECYCLE_OK' in result.stdout
    assert 'shared QObject' not in result.stderr and 'Pure virtual' not in result.stderr


def test_exclusive_commit_handles_a_concurrent_name_collision(tmp_path,monkeypatch):
    import photoprep.exporting as module
    application=app();image=QImage(160,160,QImage.Format.Format_RGB32);image.fill(QColor('green'))
    real=module.rename_exclusive
    attempts=[]
    def competing_writer(source,target):
        if not attempts:target.write_bytes(b'another writer')
        attempts.append(target)
        return real(source,target)
    monkeypatch.setattr(module,'rename_exclusive',competing_writer)
    result=module.save_clean(image,tmp_path,'photo','PNG',90)
    assert (tmp_path/'photo-photoprep.png').read_bytes()==b'another writer'
    assert result.name=='photo-photoprep-2.png'
    assert not list(tmp_path.glob('.photoprep-*.tmp'))
