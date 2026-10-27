"""Versioned local session files. No pixels, credentials or remote uploads."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, QFileDevice

from .models import Photo
from .workspace import ViewState, Workspace

MAX_SESSION_BYTES = 5 * 1024 * 1024
MAX_PHOTOS = 10000


class SessionError(ValueError):
    pass


def save_session(path: Path, workspace: Workspace) -> None:
    path = path.expanduser().resolve()
    def relative(photo_path):
        try:
            return os.path.relpath(photo_path, path.parent)
        except ValueError:
            return str(photo_path)
    document = {
        'format': 'PhotoPrep', 'version': 1,
        'selected': relative(workspace.selected) if workspace.selected else None,
        'photos': [{'path': relative(photo.path),
                    'view': asdict(workspace.views.get(photo.path, ViewState()))}
                   for photo in workspace.photos],
    }
    data = json.dumps(document, ensure_ascii=False, indent=2).encode('utf-8')
    if len(data) > MAX_SESSION_BYTES or len(workspace.photos) > MAX_PHOTOS:
        raise SessionError('session_too_large')
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if not output.setPermissions(QFileDevice.Permission.ReadOwner | QFileDevice.Permission.WriteOwner):
        output.cancelWriting()
        raise OSError(output.errorString())
    if output.write(data) != len(data):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


def _view(value) -> ViewState:
    if not isinstance(value, dict):
        return ViewState()
    try:
        zoom = float(value.get('zoom', 1))
        x = float(value.get('center_x', .5))
        y = float(value.get('center_y', .5))
        if not all(math.isfinite(v) for v in (zoom, x, y)):
            return ViewState()
        return ViewState(fit=value.get('fit', True) is not False,
                         zoom=min(16, max(.05, zoom)),
                         center_x=min(1, max(0, x)), center_y=min(1, max(0, y)))
    except (ValueError, TypeError, OverflowError):
        return ViewState()


def load_session(path: Path) -> tuple[Workspace, int]:
    path = path.expanduser().resolve()
    # Read at most the limit, including files that grow after the initial stat.
    with path.open('rb') as source:
        data = source.read(MAX_SESSION_BYTES + 1)
    if len(data) > MAX_SESSION_BYTES:
        raise SessionError('session_too_large')
    try:
        document = json.loads(data)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SessionError('session_invalid') from exc
    if (not isinstance(document, dict) or document.get('format') != 'PhotoPrep'
            or type(document.get('version')) is not int or document['version'] != 1
            or not isinstance(document.get('photos'), list)):
        raise SessionError('session_invalid')
    if len(document['photos']) > MAX_PHOTOS:
        raise SessionError('session_too_large')
    workspace = Workspace()
    skipped = 0
    known = set()
    for entry in document['photos']:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise SessionError('session_invalid')
        try:
            file = (path.parent / entry['path']).resolve()
            photo = Photo.from_path(file)
        except (OSError, ValueError, RuntimeError):
            photo = None
        if photo is None:
            skipped += 1
            continue
        if photo.path in known:
            continue
        known.add(photo.path)
        workspace.photos.append(photo)
        workspace.views[photo.path] = _view(entry.get('view'))
    selected = document.get('selected')
    try:
        selected_path = (path.parent / selected).resolve() if isinstance(selected, str) else None
    except (OSError, ValueError, RuntimeError):
        selected_path = None
    workspace.selected = selected_path if selected_path in known else (workspace.photos[0].path if workspace.photos else None)
    workspace.mark_saved()
    return workspace, skipped
