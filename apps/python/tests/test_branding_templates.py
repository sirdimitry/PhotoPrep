"""Generated assets only: no organization artwork is shipped in tests."""
from dataclasses import replace
from pathlib import Path
import json

from PIL import Image,ImageDraw
import pytest
from PySide6.QtCore import QRectF,QSettings
from PySide6.QtGui import QImage,QColor
from PySide6.QtTest import QTest
from photoprep.branding import placement_from_path,read_logo,logo_rect,template_catalog
from photoprep.editing import PhotoEdits
from photoprep.exporting import compose
from photoprep.session import save_session,load_session,SessionError
from photoprep.workspace import Workspace
from photoprep.models import Photo
from photoprep.settings import Preferences
from photoprep.ui.main_window import MainWindow


def template(path,size=(1920,1080),box=(76,67,396,186)):
    path.parent.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGBA',size)
    ImageDraw.Draw(image).rectangle((box[0],box[1],box[2]-1,box[3]-1),fill=(255,255,255,255))
    image.save(path)
    return path


def test_template_reproduces_layout_and_adapts_frame(tmp_path):
    path=template(tmp_path/'overlay.png')
    placement=placement_from_path(path);asset=read_logo(path,placement.mode)
    assert placement.mode=='template' and (asset.width(),asset.height())==(320,119)
    original=logo_rect(QRectF(0,0,1920,1080),placement,asset)
    assert (original.x(),original.y(),original.width(),original.height())==pytest.approx((76,67,320,119))
    source=QImage(800,600,QImage.Format.Format_RGBA8888);source.fill(QColor('black'))
    for width,height in ((1136,710),(1600,900),(710,1136),(128,128)):
        rect=logo_rect(QRectF(0,0,width,height),placement,asset)
        assert rect.width()/rect.height()==pytest.approx(320/119)
        assert rect.left()/(width-rect.width())==pytest.approx(76/1600)
        assert rect.top()/(height-rect.height())==pytest.approx(67/961)
        assert QRectF(0,0,width,height).contains(rect)
        result=compose(source,PhotoEdits(logo=placement),width,height)
        assert result.pixelColor(int(rect.center().x()),int(rect.center().y())).red()==255
        assert result.pixelColor(width//2,height//2).red()==0


def test_right_template_and_large_optional_asset(tmp_path):
    path=template(tmp_path/'right.png',box=(1529,68,1849,187))
    p=placement_from_path(path);asset=read_logo(path,p.mode)
    rect=logo_rect(QRectF(0,0,1920,1080),p,asset)
    assert rect.x()==pytest.approx(1529)
    large=template(tmp_path/'large.png',(6000,4000),(281,252,1446,671))
    p=placement_from_path(large);asset=read_logo(large,p.mode)
    assert (asset.width(),asset.height())==(1165,419)
    assert p.width==pytest.approx(1165/6000)


def test_local_catalog_priority_and_separate_logo(tmp_path):
    left=template(tmp_path/'16 на 9/ПРИОРИТЕТ - Горизонталь - лого слева.png')
    right=template(tmp_path/'16 на 9/Горизонталь - лого справа.png')
    template(tmp_path/'4 на 3/Горизонталь слева.png',(600,400),(30,25,130,65))
    template(tmp_path/'16 на 9/Вертикаль слева.png',(1080,1920))
    (tmp_path/'broken.png').write_text('invalid')
    entries=template_catalog(tmp_path)
    assert [e[2] for e in entries[:2]]==[left,right]
    assert len(entries)==4
    standalone=tmp_path/'mark.png';Image.new('RGBA',(324,118),'white').save(standalone)
    p=placement_from_path(standalone)
    assert p.mode=='logo' and p.x==0 and p.y==0
    assert read_logo(standalone).width()==324
    blank=tmp_path/'blank.png';Image.new('RGBA',(10,10)).save(blank)
    with pytest.raises(ValueError):placement_from_path(blank)


def test_template_session_version_and_legacy_defaults(tmp_path):
    path=template(tmp_path/'overlay.png');photo=tmp_path/'photo.png';Image.new('RGB',(320,200)).save(photo)
    workspace=Workspace();workspace.add([Photo.from_path(photo)])
    workspace.set_logo_for_all(placement_from_path(path))
    session=tmp_path/'project.photoprep.json';save_session(session,workspace)
    data=json.loads(session.read_text());assert data['version']==6
    assert not Path(data['photos'][0]['edits']['logo']['path']).is_absolute()
    restored,_=load_session(session);assert restored.snapshot()==workspace.snapshot()
    data['version']=5;data['photos'][0]['edits']['logo'].pop('mode')
    session.write_text(json.dumps(data));old,_=load_session(session)
    assert old.edits[photo].logo.mode=='logo'
    data['photos'][0]['edits']['logo']['mode']='invalid'
    session.write_text(json.dumps(data))
    with pytest.raises(SessionError):load_session(session)


def test_template_selection_gui_keeps_output_size_and_local_preferences(tmp_path,monkeypatch,qt_application_lifetime):
    left=template(tmp_path/'templates/16 на 9/ПРИОРИТЕТ - Горизонталь - лого слева.png')
    right=template(tmp_path/'templates/16 на 9/Горизонталь - лого справа.png')
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    prefs.logo_folder=str(tmp_path/'templates');prefs.output_width=1136;prefs.output_height=710
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    photo=tmp_path/'photo.png';Image.new('RGB',(800,600),'#34485a').save(photo)
    window=MainWindow();window._confirm_discard=lambda:True;window.show();window.import_paths([str(photo)])
    for _ in range(400):
        if not window.canvas.loading:break
        QTest.qWait(10)
    try:
        assert not window.canvas.loading
        assert window.logo_library.itemData(1)==str(left)
        window._select_tool('logo');window._choose_catalog_logo(1)
        assert window.workspace.edits[photo].logo.mode=='template'
        assert (window.workspace.output_width,window.workspace.output_height)==(1136,710)
        window._choose_catalog_logo(2)
        assert window.workspace.edits[photo].logo.path==str(right)
        window.undo();assert window.workspace.edits[photo].logo.path==str(left)
        window.settings.language='en';window.retranslate()
        assert 'Top left' in window.logo_library.itemText(1)
        window.settings.language='ru';window.retranslate()
        assert 'Слева' in window.logo_library.itemText(1)
    finally:window.close()
