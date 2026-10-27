"""Persist only user preferences, never modify original images."""

from __future__ import annotations

from PySide6.QtCore import QLocale, QSettings


class Preferences:
    def __init__(self, store: QSettings | None = None) -> None:
        self._q = store if store is not None else QSettings("sirdimitry", "PhotoPrep")

    def _dimension(self, key: str, default: int) -> int:
        try:
            value = int(self._q.value(key, default))
        except (TypeError, ValueError, OverflowError):
            return default
        return value if 128 <= value <= 16000 else default

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
        return self._dimension("export/width", 1136)

    @output_width.setter
    def output_width(self, value: int) -> None:
        self._q.setValue("export/width", int(value))

    @property
    def output_height(self) -> int:
        return self._dimension("export/height", 710)

    @output_height.setter
    def output_height(self, value: int) -> None:
        self._q.setValue("export/height", int(value))
