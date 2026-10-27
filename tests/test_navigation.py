"""UI regressions for background decoding, Retina zoom and workspace navigation."""
import hashlib
import threading
import time

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from photoprep.settings import Preferences
from photoprep.ui.canvas import PhotoCanvas, DecodePhoto
from photoprep.ui.main_window import MainWindow
from photoprep.workspace import ViewState


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    return application


def wait_for(predicate, timeout=5000):
    end = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < end:
        QTest.qWait(10)
    assert predicate(), 'UI operation timed out'


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    prefs = Preferences(QSettings(str(tmp_path/'prefs.ini'), QSettings.Format.IniFormat))
    monkeypatch.setattr('photoprep.ui.main_window.Preferences', lambda: prefs)
    result = MainWindow()
    result._confirm_discard = lambda: True
    result.show()
    app.processEvents()
    yield result
    result.canvas.clear_photo()
    assert result.canvas._pool.waitForDone(5000)
    result._confirm_discard = lambda: True
    result.close()
    app.processEvents()


@pytest.fixture
def images(tmp_path):
    paths = []
    for name, color in [('первое.png', 'yellow'), ('second.png', 'blue')]:
        path = tmp_path/name
        Image.new('RGB', (1600,1200), color).save(path)
        paths.append(path)
    return paths


def test_navigation_restores_view_and_undo_never_deletes(window, images):
    hashes = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in images}
    assert window.import_paths([str(p) for p in images]) == 2
    wait_for(lambda: not window.canvas.loading)
    window.canvas.actual_size()
    assert window.zoom_value.text() == '100%'
    window.canvas.zoom(2)
    window.canvas.centerOn(1000, 800)
    before = window.canvas.view_state()
    window.navigate(1)
    wait_for(lambda: not window.canvas.loading)
    assert window.workspace.index == 1
    window.navigate(-1)
    wait_for(lambda: not window.canvas.loading)
    after = window.canvas.view_state()
    assert after.zoom == pytest.approx(before.zoom)
    assert after.center_x == pytest.approx(before.center_x, abs=.003)
    assert after.center_y == pytest.approx(before.center_y, abs=.003)
    window.remove_photo()
    wait_for(lambda: not window.canvas.loading)
    assert len(window.photos) == 1
    window.undo()
    wait_for(lambda: not window.canvas.loading)
    assert len(window.photos) == 2
    assert window.workspace.index == 0
    assert window.canvas.view_state().zoom == pytest.approx(before.zoom)
    window.redo()
    wait_for(lambda: not window.canvas.loading)
    window.remove_photo()
    assert not window.photos and not window.canvas.has_photo
    assert window.stack.currentWidget() == window.empty
    assert not window.next_button.isEnabled()
    assert hashes == {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in images}


def test_save_open_and_language_switch(window, images, tmp_path):
    window.import_paths([str(p) for p in images])
    wait_for(lambda: not window.canvas.loading)
    window.canvas.actual_size()
    window.navigate(1)
    wait_for(lambda: not window.canvas.loading)
    session = tmp_path/'shoot.photoprep.json'
    window.session_path = session
    assert window.save_workspace()
    assert not window.workspace.dirty
    window.new_workspace()
    assert not window.photos
    assert window.open_session_file(session)
    wait_for(lambda: not window.canvas.loading)
    assert window.workspace.index == 1
    assert not window.workspace.dirty
    window.settings.language = 'ru'
    window.retranslate()
    assert window.actions['save_workspace'].text() == 'Сохранить набор'
    assert window.next_button.accessibleName() == 'Следующее фото'
    assert window.photo_position.text() == '2 из 2'
    window.navigate(-1)
    wait_for(lambda: not window.canvas.loading)
    assert window.zoom_value.text() == '100%'


def test_cancel_close_keeps_workspace(window, images, monkeypatch):
    window.import_paths([str(images[0])])
    wait_for(lambda: not window.canvas.loading)
    monkeypatch.setattr(window, '_confirm_discard', MainWindow._confirm_discard.__get__(window))
    def cancel():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        for button in box.buttons():
            if box.buttonRole(button) == QMessageBox.ButtonRole.RejectRole:
                button.click()
                return
        pytest.fail('No cancel button')
    QTimer.singleShot(20, cancel)
    window.close()
    assert window.isVisible()
    assert len(window.photos) == 1


def test_late_decode_cannot_replace_new_selection(app, images, monkeypatch):
    release = threading.Event()
    original = DecodePhoto.run
    def controlled(self):
        if self.path == str(images[0]):
            release.wait(5)
        original(self)
    monkeypatch.setattr(DecodePhoto, 'run', controlled)
    canvas = PhotoCanvas()
    canvas.show()
    try:
        canvas.load_photo(str(images[0]))
        # Let the first worker start, so it cannot simply be removed from the queue.
        QTest.qWait(30)
        canvas.load_photo(str(images[1]))
        wait_for(lambda: canvas.current_path == str(images[1]))
        release.set()
        assert canvas._pool.waitForDone(5000)
        app.processEvents()
        assert canvas.current_path == str(images[1])
        assert len(canvas._workers) == 0
    finally:
        release.set()
        canvas._pool.waitForDone(5000)
        canvas.close()


def test_changed_file_invalidates_bounded_image_cache(app, tmp_path):
    path = tmp_path/'changing.png'
    Image.new('RGB',(30,20),'yellow').save(path)
    canvas = PhotoCanvas()
    canvas.cache_limit = 4000
    canvas.show()
    try:
        canvas.load_photo(str(path))
        wait_for(lambda: not canvas.loading)
        assert canvas._pixmap_item.pixmap().width() == 30
        Image.new('RGB',(40,20),'blue').save(path)
        canvas.load_photo(str(path))
        wait_for(lambda: not canvas.loading)
        assert canvas._pixmap_item.pixmap().width() == 40
        assert canvas._cache_bytes <= canvas.cache_limit
        canvas.actual_size()
        canvas.zoom(float('inf'))
        assert canvas.view_state().zoom == pytest.approx(1)
        canvas.zoom(100000)
        assert canvas.view_state().zoom == pytest.approx(16)
        canvas.zoom(.000001)
        assert canvas.view_state().zoom == pytest.approx(.05)
    finally:
        canvas._pool.waitForDone(5000)
        canvas.close()


def test_restored_zoom_is_not_marked_dirty_by_new_window_size(window, images, tmp_path):
    window.import_paths([str(images[0])])
    wait_for(lambda: not window.canvas.loading)
    window.canvas.actual_size()
    window.canvas.zoom(.5)
    window.session_path = tmp_path/'position.photoprep.json'
    assert window.save_workspace()
    window.new_workspace()
    window.resize(980, 650)
    QApplication.processEvents()
    assert window.open_session_file(tmp_path/'position.photoprep.json')
    wait_for(lambda: not window.canvas.loading)
    assert window.canvas.view_state().zoom == pytest.approx(.5)
    window._capture_view()
    assert not window.workspace.dirty


def test_failed_save_keeps_existing_file_and_dirty_workspace(window, images, tmp_path, monkeypatch):
    window.import_paths([str(images[0])])
    wait_for(lambda: not window.canvas.loading)
    session = tmp_path/'safe.photoprep.json'
    window.session_path = session
    assert window.save_workspace()
    original = session.read_bytes()
    window.remove_photo()
    def fail(*args):
        raise OSError('simulated unwritable folder')
    monkeypatch.setattr('photoprep.ui.main_window.save_session', fail)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: QMessageBox.StandardButton.Ok)
    assert not window.save_workspace()
    assert window.workspace.dirty
    assert session.read_bytes() == original


def test_missing_source_clears_previous_preview(window, images):
    window.import_paths([str(p) for p in images])
    wait_for(lambda: not window.canvas.loading)
    images[1].unlink()
    window.navigate(1)
    wait_for(lambda: not window.canvas.loading)
    assert window.workspace.index == 1
    assert not window.canvas.has_photo
    assert window.canvas.current_path is None
    assert 'second.png' in window.statusBar().currentMessage()


def test_undecodable_existing_file_reports_failure(app, tmp_path):
    path = tmp_path/'broken.png'
    path.write_text('not an image')
    canvas = PhotoCanvas()
    results = []
    canvas.photo_loaded.connect(lambda path, success: results.append(success))
    try:
        canvas.load_photo(str(path))
        wait_for(lambda: bool(results))
        assert results == [False]
        assert not canvas.has_photo and not canvas.loading
    finally:
        canvas._pool.waitForDone(5000)
        canvas.close()
