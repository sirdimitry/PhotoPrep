"""Regression coverage for import, navigation and persistent bilingual preferences."""
import hashlib

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from photoprep.models import Photo
from photoprep.settings import Preferences
from photoprep.ui.main_window import MainWindow
from photoprep.ui.preferences_dialog import PreferencesDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def preferences(tmp_path):
    return Preferences(QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat))


def test_preferences_recover_and_persist(preferences):
    preferences._q.setValue("export/width", "broken")
    preferences._q.setValue("export/height", -1)
    assert (preferences.output_width, preferences.output_height) == (1136, 710)
    preferences.language = "ru"
    preferences.output_width = 1920
    preferences.output_height = 1080
    preferences._q.sync()
    reopened = Preferences(QSettings(preferences._q.fileName(), QSettings.Format.IniFormat))
    assert (reopened.language, reopened.output_width, reopened.output_height) == ("ru", 1920, 1080)


def test_workspace_import_zoom_and_language(app, preferences, monkeypatch, tmp_path):
    monkeypatch.setattr("photoprep.ui.main_window.Preferences", lambda: preferences)
    source = tmp_path / "фотография.png"
    Image.new("RGB", (1600, 900), "#facc15").save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    window = MainWindow()
    window.show()
    app.processEvents()
    try:
        preferences.language = "en"
        window.retranslate()
        assert window.statusBar().currentMessage() == "Open photos to start"
        window.import_paths([str(source), str(source)])
        app.processEvents()
        assert len(window.photos) == 1
        assert window.canvas.has_photo
        assert window.source_value.text() == "1600 × 900 px"
        assert not window.export_button.isEnabled()
        window.canvas.actual_size()
        assert window.canvas.transform().m11() == 1
        window.canvas.zoom(1.15)
        assert window.canvas.transform().m11() == pytest.approx(1.15)
        window.canvas.fit_photo()
        assert window.canvas.transform().m11() < 1
        preferences.language = "ru"
        window.retranslate()
        assert window.open_files_button.text() == "Открыть фото"
        assert window.statusBar().currentMessage() == "Загружено фотографий: 1"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    finally:
        window.close()


def test_settings_cancel_and_apply(app, preferences):
    preferences.language = "ru"
    dialog = PreferencesDialog(preferences)
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Отмена"
    dialog.width_input.setValue(2000)
    dialog.reject()
    assert preferences.output_width == 1136
    dialog = PreferencesDialog(preferences)
    dialog.language.setCurrentIndex(dialog.language.findData("en"))
    dialog.width_input.setValue(1920)
    dialog.height_input.setValue(1080)
    dialog.apply_and_close()
    assert (preferences.language, preferences.output_width, preferences.output_height) == ("en", 1920, 1080)


def test_exif_oriented_dimensions(tmp_path):
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (120, 80), "yellow").save(source, exif=exif)
    photo = Photo.from_path(source)
    assert (photo.width, photo.height) == (80, 120)
