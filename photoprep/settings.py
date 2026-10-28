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

    @property
    def appearance(self) -> str:
        value = self._q.value("ui/appearance", "dark")
        return value if value in ("dark", "light") else "dark"

    @appearance.setter
    def appearance(self, value: str) -> None:
        if value not in ("dark", "light"):
            raise ValueError("Unsupported appearance")
        self._q.setValue("ui/appearance", value)

    @property
    def model_id(self):
        from .catalog import MODELS, DEFAULT_MODEL
        value = self._q.value('ai/model',DEFAULT_MODEL)
        return value if isinstance(value,str) and value in MODELS else DEFAULT_MODEL

    @model_id.setter
    def model_id(self,value):
        from .catalog import get_model
        get_model(value)
        self._q.setValue('ai/model',value)

    def model_source(self,model_id):
        from .catalog import get_model
        get_model(model_id)
        value=self._q.value('models/local_source/'+model_id,'')
        return value if isinstance(value,str) and '\x00' not in value else ''

    def set_model_source(self,model_id,value):
        from .catalog import get_model
        get_model(model_id)
        self._q.setValue('models/local_source/'+model_id,str(value))

    @property
    def logo_folder(self):
        value=self._q.value('branding/logo_folder','')
        return value if isinstance(value,str) and '\x00' not in value else ''

    @logo_folder.setter
    def logo_folder(self,value):
        self._q.setValue('branding/logo_folder',str(value))

    @property
    def logo_path(self):
        value=self._q.value('branding/logo_path','')
        return value if isinstance(value,str) else ''

    @logo_path.setter
    def logo_path(self,value):
        self._q.setValue('branding/logo_path',str(value))

    @property
    def export_format(self):
        value=self._q.value('export/format','JPEG')
        return value if value in ('JPEG','PNG') else 'JPEG'

    @export_format.setter
    def export_format(self,value):
        if value not in ('JPEG','PNG'):raise ValueError('Invalid format')
        self._q.setValue('export/format',value)

    @property
    def export_quality(self):
        try:value=int(self._q.value('export/quality',90))
        except (TypeError,ValueError):return 90
        return value if 1<=value<=100 else 90

    @export_quality.setter
    def export_quality(self,value):
        self._q.setValue('export/quality',max(1,min(100,int(value))))
