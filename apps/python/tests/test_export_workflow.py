"""Source-adjacent export naming and the single comparison control."""
from dataclasses import replace
import hashlib,json,time
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QPushButton
from photoprep.models import Photo
from photoprep.workspace import Workspace
from photoprep.session import save_session
from photoprep.settings import Preferences
from photoprep.exporting import export_job,signature
from photoprep.editing import PhotoEdits,CropRect,MaskStroke
from photoprep.ui.main_window import MainWindow
from photoprep.ui.export_dialog import ExportDialog


def photo(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    Image.new('RGB',(800,600),'#204080').save(path)
    return Photo.from_path(path)


def export(tmp_path,photos):
    workspace=Workspace(output_width=160,output_height=128);workspace.add(photos)
    session=tmp_path/'set.photoprep.json';save_session(session,workspace)
    request=tmp_path/'request.json';request.write_text(json.dumps({'session':str(session),'sources':{str(p.path):signature(p.path) for p in photos},'protected':[str(p.path) for p in photos],'logos':{},'models':{},'format':'PNG','quality':90}))
    export_job(request)


def test_single_export_names_and_collision_skip(tmp_path,qt_application_lifetime):
    source=photo(tmp_path/'photo.png');digest=hashlib.sha256(source.path.read_bytes()).digest()
    export(tmp_path,[source]);assert (tmp_path/'photo-logo.png').is_file()
    (tmp_path/'photo-logo01.png').write_bytes(b'keep existing')
    export(tmp_path,[source]);assert (tmp_path/'photo-logo02.png').is_file()
    assert (tmp_path/'photo-logo01.png').read_bytes()==b'keep existing'
    assert hashlib.sha256(source.path.read_bytes()).digest()==digest
    assert not (tmp_path/'PhotoPrep Export').exists()


def test_batch_saves_in_each_source_folder_and_never_replaces(tmp_path,qt_application_lifetime):
    first=photo(tmp_path/'one/photo.png');second=photo(tmp_path/'two/photo.jpg')
    existing=tmp_path/'one/photo-logo01.png';existing.write_bytes(b'existing 1')
    (tmp_path/'one/photo-logo02.png').write_bytes(b'existing 2')
    originals={p.path:hashlib.sha256(p.path.read_bytes()).digest() for p in (first,second)}
    export(tmp_path,[first,second])
    assert (tmp_path/'one/photo-logo03.png').is_file()
    assert (tmp_path/'two/photo-logo02.png').is_file()
    assert existing.read_bytes()==b'existing 1'
    assert all(hashlib.sha256(path.read_bytes()).digest()==digest for path,digest in originals.items())
    assert not list(tmp_path.rglob('.photoprep-*.tmp'))


def window(tmp_path,monkeypatch):
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    prefs.language='ru';monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    source=photo(tmp_path/'source.png');w=MainWindow();w._confirm_discard=lambda:True;w.show();w.import_paths([str(source.path)])
    for _ in range(400):
        if not w.canvas.loading:break
        QTest.qWait(10)
    assert not w.canvas.loading
    return w,source


def test_export_dialog_has_no_destination_picker(tmp_path,monkeypatch,qt_application_lifetime):
    w,source=window(tmp_path,monkeypatch)
    try:
        dialog=ExportDialog(w.workspace,w.settings,w)
        assert not dialog.findChildren(QLineEdit)
        assert not hasattr(dialog,'browse')
        assert 'Рядом' in dialog.destination.text() or 'рядом' in dialog.destination.text()
        assert dialog.start_button.isEnabled()
        dialog.reject()
    finally:w.close()


def test_single_compare_control_works_for_crop_and_pending_mask(tmp_path,monkeypatch,qt_application_lifetime):
    w,source=window(tmp_path,monkeypatch)
    try:
        button=w.tools['compare'];assert button.isCheckable() and not button.isEnabled()
        assert not any(b.text() in ('До','После','Before','After') for b in w.findChildren(QPushButton))
        crop=CropRect(.15,.2,.5,.5/(1136/710)*800/600)
        edits=PhotoEdits(strokes=(MaskStroke(((.5,.5),),.1),),crop=crop)
        w.canvas.set_edits(edits);w._edits_committed(source.path,edits)
        assert button.isEnabled() and button.isChecked()
        assert w.canvas._mask_overlay.isVisible()
        after_frame=w.canvas.output_frame_rect
        button.click()
        assert not button.isChecked() and w.canvas._comparison_before
        assert not w.canvas._mask_overlay.isVisible()
        assert w.canvas.output_frame_rect!=after_frame
        assert w.workspace.edits[source.path]==edits
        button.click()
        assert button.isChecked() and not w.canvas._comparison_before
        assert w.canvas._mask_overlay.isVisible() and w.canvas.output_frame_rect==after_frame
        assert w.workspace.edits[source.path]==edits
        w.settings.output_width=1600;w.settings.output_height=900;w._preferences_applied()
        assert button.isEnabled() and button.isChecked()
    finally:w.close()
