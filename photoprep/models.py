"""Read-only source image model. Destructive editing will be a separate stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QImageReader

SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"})


@dataclass(frozen=True)
class Photo:
    path: Path
    width: int
    height: int

    @classmethod
    def from_path(cls, path: str | Path) -> "Photo | None":
        file = Path(path).expanduser().resolve()
        if not file.is_file() or file.suffix.lower() not in SUPPORTED_SUFFIXES:
            return None
        reader = QImageReader(str(file))
        reader.setAutoTransform(True)
        size = reader.size()
        # Some decoders only report dimensions after decoding.
        if not size.isValid():
            image = reader.read()
            if image.isNull():
                return None
            size = image.size()
        return cls(file, size.width(), size.height())


def list_folder_images(folder: str | Path) -> list[Path]:
    root = Path(folder).expanduser()
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES), key=lambda p: p.name.casefold())
