"""Non-destructive workspace state and bounded collection history."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .models import Photo
from .editing import PhotoEdits, fit_crop


@dataclass(frozen=True)
class ViewState:
    fit: bool = True
    zoom: float = 1.0  # physical screen pixels per source pixel
    center_x: float = 0.5
    center_y: float = 0.5


@dataclass
class Snapshot:
    photos: tuple[Photo, ...]
    selected: Path | None
    views: dict[Path, ViewState]
    edits: dict[Path, PhotoEdits]
    output_size: tuple[int, int]


@dataclass
class Workspace:
    photos: list[Photo] = field(default_factory=list)
    selected: Path | None = None
    views: dict[Path, ViewState] = field(default_factory=dict)
    edits: dict[Path, PhotoEdits] = field(default_factory=dict)
    output_width: int = 1136
    output_height: int = 710
    _undo: list[Snapshot] = field(default_factory=list, repr=False)
    _redo: list[Snapshot] = field(default_factory=list, repr=False)
    _saved: Snapshot | None = field(default=None, repr=False)

    def __post_init__(self):
        self.mark_saved()

    def snapshot(self) -> Snapshot:
        return Snapshot(tuple(self.photos), self.selected, dict(self.views), dict(self.edits), (self.output_width,self.output_height))

    def mark_saved(self) -> None:
        self._saved = self.snapshot()

    @property
    def dirty(self) -> bool:
        return self.snapshot() != self._saved

    @property
    def index(self) -> int:
        return next((i for i, p in enumerate(self.photos) if p.path == self.selected), -1)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _checkpoint(self) -> None:
        self._undo.append(self.snapshot())
        self._undo = self._undo[-100:]
        self._redo.clear()

    def add(self, photos: list[Photo]) -> int:
        known = {p.path for p in self.photos}
        added = []
        for photo in photos:
            if photo.path not in known:
                added.append(photo)
                known.add(photo.path)
        if not added:
            return 0
        self._checkpoint()
        self.photos.extend(added)
        for photo in added:
            self.views[photo.path] = ViewState()
            self.edits[photo.path] = PhotoEdits()
        if self.selected is None:
            self.selected = added[0].path
        return len(added)

    def remove_selected(self) -> bool:
        index = self.index
        if index < 0:
            return False
        self._checkpoint()
        removed = self.photos.pop(index)
        self.views.pop(removed.path, None)
        self.edits.pop(removed.path, None)
        self.selected = self.photos[min(index, len(self.photos) - 1)].path if self.photos else None
        return True

    def set_edits(self, path: Path, edits: PhotoEdits) -> bool:
        if not any(p.path == path for p in self.photos) or self.edits.get(path, PhotoEdits()) == edits:
            return False
        self._checkpoint()
        self.edits[path] = edits
        return True

    def set_logo_for_all(self,logo):
        if not any(self.edits.get(photo.path,PhotoEdits()).logo!=logo for photo in self.photos):
            return False
        self._checkpoint()
        for photo in self.photos:
            self.edits[photo.path]=replace(self.edits.get(photo.path,PhotoEdits()),logo=logo)
        return True

    def set_output_size(self, width: int, height: int) -> bool:
        if not (128 <= width <= 16000 and 128 <= height <= 16000):
            raise ValueError('Unsupported output dimensions')
        if (width, height) == (self.output_width, self.output_height):
            return False
        self._checkpoint()
        self.output_width, self.output_height = width, height
        for photo in self.photos:
            edits = self.edits.get(photo.path, PhotoEdits())
            if edits.crop is not None:
                self.edits[photo.path] = replace(edits, crop=fit_crop(photo.width,photo.height,width/height,edits.crop))
        return True

    def _restore(self, snapshot: Snapshot) -> None:
        self.photos = list(snapshot.photos)
        self.selected = snapshot.selected
        self.views = dict(snapshot.views)
        self.edits = dict(snapshot.edits)
        self.output_width, self.output_height = snapshot.output_size

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.snapshot())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.snapshot())
        self._restore(self._redo.pop())
        return True
