"""Persist only user preferences, never modify original images."""

from __future__ import annotations

from PySide6.QtCore import QLocale, QSettings


class Preferences:
    def __init__(self) -> None:
        self._q = QSettings("sirdimitry", "PhotoPrep")

    @property
    def language(self) -> str:
        default = "ru" if QLocale.system().name().lower().startswith("ru") else "en"
        value = self._q.value("ui/language", default)
        return value if value in ("ru", "en") else default

    @language.setter
    def language(self, value: str) -> None:
        if value not in ("ru", "en"):
            raise ValueError("Unsupported language")
        self._q.setValue("ui/language", value)

    @property
    def output_width(self) -> int:
        return int(self._q.value("export/width", 1136))

    @output_width.setter
    def output_width(self, value: int) -> None:
        self._q.setValue("export/width", int(value))

    @property
    def output_height(self) -> int:
        return int(self._q.value("export/height", 710))

    @output_height.setter
    def output_height(self, value: int) -> None:
        self._q.setValue("export/height", int(value))
