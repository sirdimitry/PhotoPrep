"""Compact settings dialog, with infrequently used output size tucked away."""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QToolButton, QWidget)

from ..i18n import tr
from ..settings import Preferences


class PreferencesDialog(QDialog):
    applied = Signal()

    def __init__(self, settings: Preferences, parent=None):
        super().__init__(parent)
        self.settings = settings
        t = lambda k: tr(settings.language, k)
        self.setWindowTitle(t("preferences_title"))
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 18)
        root.setSpacing(18)

        general = QGroupBox(t("general"))
        form = QFormLayout(general)
        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("Русский", "ru")
        self.language.setCurrentIndex(self.language.findData(settings.language))
        form.addRow(t("language"), self.language)
        root.addWidget(general)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("▸  " + t("output_advanced"))
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        root.addWidget(self.advanced_toggle)
        advanced = QWidget()
        adv_form = QFormLayout(advanced)
        self.width_input = QSpinBox()
        self.height_input = QSpinBox()
        for spin in (self.width_input, self.height_input):
            spin.setRange(128, 16000)
        self.width_input.setValue(settings.output_width)
        self.height_input.setValue(settings.output_height)
        adv_form.addRow(t("width"), self.width_input)
        adv_form.addRow(t("height"), self.height_input)
        hint = QLabel(t("dimensions_hint"))
        hint.setWordWrap(True)
        hint.setObjectName("SmallHint")
        adv_form.addRow(hint)
        advanced.setVisible(False)
        self.advanced_toggle.toggled.connect(advanced.setVisible)
        root.addWidget(advanced)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.apply_and_close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def apply_and_close(self):
        self.settings.language = self.language.currentData()
        self.settings.output_width = self.width_input.value()
        self.settings.output_height = self.height_input.value()
        self.applied.emit()
        self.accept()
