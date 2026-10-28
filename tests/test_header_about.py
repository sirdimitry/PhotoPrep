from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from photoprep.ui.widgets import PhotoNameLabel
from photoprep.ui.main_window import MainWindow
from photoprep.ui.preferences_dialog import PreferencesDialog
from photoprep.settings import Preferences


def test_full_name_uses_available_width_and_middle_elision_is_reversible(qt_application_lifetime):
    label=PhotoNameLabel();name='photo_2026-10-27_16-24-09.jpg'
    label.resize(600,30);label.show();label.set_filename(name);QTest.qWait(10)
    try:
        assert label.text()==name
        label.resize(150,30);QTest.qWait(10)
        assert '...' in label.text() and label.text().startswith('photo') and label.text().endswith('.jpg')
        assert label.fontMetrics().horizontalAdvance(label.text())<=label.contentsRect().width()
        assert label.toolTip()==name and label.accessibleName()==name
        label.resize(600,30);QTest.qWait(10);assert label.text()==name
        label.set_filename('Это длинное имя фотографии с пробелами.jpg')
        assert label.text()=='Это длинное имя фотографии с пробелами.jpg'
    finally:label.close()


def test_import_starts_mask_and_header_extends_to_open_button(tmp_path,monkeypatch,qt_application_lifetime):
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences',lambda:prefs)
    name='photo_2026-10-27_16-24-09.jpg';source=tmp_path/name;Image.new('RGB',(800,600),'blue').save(source)
    w=MainWindow();w._confirm_discard=lambda:True;w.resize(1440,900);w.show();w.import_paths([str(source)])
    for _ in range(400):
        if not w.canvas.loading:break
        QTest.qWait(10)
    try:
        assert not w.canvas.loading and w.canvas.tool=='mask'
        assert w.tool_options.height()<240
        assert list(w.tools)==['mask','erase','crop','select','logo','compare']
        assert w.photo_label.text()==name
        assert 0<w.open_files_button.geometry().left()-w.photo_label.geometry().right()<=12
        w._select_tool('crop');assert w.canvas.tool=='crop'
        w._select_tool('logo');assert w.canvas.tool=='logo'
        w.retranslate();assert w.canvas.tool=='logo'
    finally:w.close()


def test_about_has_mit_logo_notice_and_public_author_link_in_both_languages(tmp_path,qt_application_lifetime):
    prefs=Preferences(QSettings(str(tmp_path/'prefs.ini'),QSettings.Format.IniFormat));prefs.language='ru'
    dialog=PreferencesDialog(prefs);dialog.show();dialog.tabs.setCurrentIndex(2)
    try:
        assert dialog.tabs.tabText(2)=='О программе'
        assert 'MIT License' in dialog.license_text.toPlainText()
        assert 'Copyright (c) 2026 sirdimitry' in dialog.license_text.toPlainText()
        assert 'Сторонние логотипы' in dialog.about_logos.text() and 'не входят в релиз' in dialog.about_logos.text()
        assert 'https://x.com/sirdimitry' in dialog.about_author.text() and '@sirdimitry' in dialog.about_author.text()
        assert dialog.about_author.openExternalLinks()
        dialog.language_buttons['en'].click()
        assert dialog.tabs.tabText(2)=='About' and 'MIT' in dialog.about_license.text()
        assert 'No third-party logos' in dialog.about_logos.text()
        dialog.reject();assert prefs.language=='ru'
    finally:dialog.close()
