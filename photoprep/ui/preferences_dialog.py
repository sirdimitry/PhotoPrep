"""Roomy bilingual settings with an immediate, uncommitted language preview."""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QLineEdit, QButtonGroup, QDialog, QDialogButtonBox, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QToolButton, QSizePolicy,
)

from ..i18n import tr
from ..settings import Preferences
from .theme import stylesheet


class DimensionInput(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setValidator(QIntValidator(128, 16000, self))
        self.setObjectName("DimensionInput")
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumWidth(160)
        self.setFixedHeight(42)
        self.setTextMargins(14, 0, 14, 0)

    def setValue(self, value):
        self.setText(str(max(128, min(16000, int(value)))))

    def value(self):
        value, valid = self.validator().locale().toInt(self.text())
        if not valid:
            raise ValueError("Invalid output dimension")
        return value


class PreferencesDialog(QDialog):
    applied = Signal()

    def __init__(self, settings: Preferences, parent=None, *, dimensions=None):
        super().__init__(parent)
        self.settings = settings
        self.setStyleSheet(stylesheet(settings.appearance))
        self.setFixedWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 22)
        root.setSpacing(20)

        self.general = QGroupBox()
        self.general.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        general_layout = QVBoxLayout(self.general)
        general_layout.setContentsMargins(16, 24, 16, 16)
        general_layout.setSpacing(12)
        self.language_label = QLabel()
        general_layout.addWidget(self.language_label)
        language_row = QHBoxLayout()
        language_row.setSpacing(10)
        self.language_group = QButtonGroup(self)
        self.language_buttons = {}
        for code, label in (("en", "English"), ("ru", "Русский")):
            button = QPushButton(label)
            button.setObjectName("LanguageChoice")
            button.setCheckable(True)
            button.setMinimumHeight(40)
            button.setChecked(code == settings.language)
            self.language_group.addButton(button)
            self.language_buttons[code] = button
            language_row.addWidget(button, stretch=1)
            button.toggled.connect(lambda checked: self.retranslate() if checked else None)
        general_layout.addLayout(language_row)
        self.appearance_label = QLabel()
        general_layout.addWidget(self.appearance_label)
        appearance_row = QHBoxLayout()
        appearance_row.setSpacing(10)
        self.appearance_group = QButtonGroup(self)
        self.appearance_buttons = {}
        for code in ('dark','light'):
            button = QPushButton()
            button.setObjectName('LanguageChoice')
            button.setCheckable(True)
            button.setMinimumHeight(32)
            button.setChecked(code == settings.appearance)
            self.appearance_group.addButton(button)
            self.appearance_buttons[code] = button
            appearance_row.addWidget(button,stretch=1)
            button.toggled.connect(lambda checked: self.setStyleSheet(stylesheet(self.selected_appearance)) if checked else None)
        general_layout.addLayout(appearance_row)
        root.addWidget(self.general)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("SettingsDisclosure")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.advanced_toggle.setMinimumHeight(38)
        root.addWidget(self.advanced_toggle)
        self.advanced = QFrame()
        self.advanced.setObjectName("SettingsCard")
        advanced_layout = QGridLayout(self.advanced)
        advanced_layout.setContentsMargins(18, 18, 18, 18)
        advanced_layout.setHorizontalSpacing(24)
        advanced_layout.setVerticalSpacing(14)
        advanced_layout.setColumnStretch(1, 1)
        self.width_label, self.height_label = QLabel(), QLabel()
        self.width_input, self.height_input = DimensionInput(), DimensionInput()
        width, height = dimensions or (settings.output_width, settings.output_height)
        self.width_input.setValue(width)
        self.height_input.setValue(height)
        self.width_label.setBuddy(self.width_input)
        self.height_label.setBuddy(self.height_input)
        advanced_layout.addWidget(self.width_label, 0, 0)
        advanced_layout.addWidget(self.width_input, 0, 1)
        advanced_layout.addWidget(self.height_label, 1, 0)
        advanced_layout.addWidget(self.height_input, 1, 1)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("SmallHint")
        advanced_layout.addWidget(self.hint, 2, 0, 1, 2)
        self.advanced.setVisible(False)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        root.addWidget(self.advanced)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        for button in self.buttons.buttons():
            button.setMinimumSize(112, 40)
        self.buttons.accepted.connect(self.apply_and_close)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        for field in (self.width_input, self.height_input):
            field.textChanged.connect(self._validate)
        self._validate()
        self.retranslate()

    def _validate(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.width_input.hasAcceptableInput() and self.height_input.hasAcceptableInput())

    @property
    def selected_language(self):
        return next(code for code, button in self.language_buttons.items() if button.isChecked())

    @property
    def selected_appearance(self):
        return next(code for code,button in self.appearance_buttons.items() if button.isChecked())

    def _toggle_advanced(self, checked):
        self.advanced.setVisible(checked)
        self.retranslate()
        self.layout().activate()
        self.adjustSize()

    def retranslate(self):
        t = lambda key: tr(self.selected_language, key)
        self.setWindowTitle(t("preferences_title"))
        self.general.setTitle(t("general"))
        self.language_label.setText(t("language"))
        self.appearance_label.setText(t('appearance'))
        for code,button in self.appearance_buttons.items():
            button.setText(t(code+'_theme'))
        self.advanced_toggle.setText(("▾  " if self.advanced_toggle.isChecked() else "▸  ") + t("output_advanced"))
        self.width_label.setText(t("width"))
        self.height_label.setText(t("height"))
        self.hint.setText(t("dimensions_hint"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("cancel"))

    def apply_and_close(self):
        if not (self.width_input.hasAcceptableInput() and self.height_input.hasAcceptableInput()):
            return
        self.settings.appearance = self.selected_appearance
        self.settings.language = self.selected_language
        self.settings.output_width = self.width_input.value()
        self.settings.output_height = self.height_input.value()
        self.applied.emit()
        self.accept()
