from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from photoprep.settings import Preferences
from photoprep.ui.preferences_dialog import PreferencesDialog


def test_language_preview_is_complete_and_cancel_does_not_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    prefs = Preferences(QSettings(str(tmp_path/'prefs.ini'), QSettings.Format.IniFormat))
    prefs.language = 'en'
    dialog = PreferencesDialog(prefs)
    dialog.show()
    app.processEvents()
    QTest.mouseClick(dialog.language_buttons['ru'], Qt.MouseButton.LeftButton)
    assert dialog.windowTitle() == 'Настройки'
    assert dialog.general.title() == 'Основные'
    assert dialog.width_label.text() == 'Ширина (пикс.)'
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == 'Отмена'
    assert prefs.language == 'en'
    en = dialog.language_buttons['en'].geometry()
    ru = dialog.language_buttons['ru'].geometry()
    assert not en.intersects(ru)
    assert ru.width() >= dialog.language_buttons['ru'].fontMetrics().horizontalAdvance('Русский') + 30
    dialog.advanced_toggle.click()
    app.processEvents()
    assert dialog.advanced.isVisible()
    assert dialog.width_input.alignment() & Qt.AlignmentFlag.AlignRight
    assert dialog.width_input.textMargins().right() >= 12
    assert not dialog.width_label.geometry().intersects(dialog.width_input.geometry())
    dialog.language_buttons["en"].setChecked(True)
    assert dialog.windowTitle() == "Preferences"
    dialog.width_input.setText("12")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.width_input.setText("1920")
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.reject()
    assert prefs.language == 'en'
