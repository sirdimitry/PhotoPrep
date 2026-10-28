"""Versioned local session files. No pixels, credentials or remote uploads."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, replace
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile, QFileDevice

from .branding import LogoPlacement
from .catalog import MODELS
from .models import Photo
from .editing import PhotoEdits, MaskStroke, CropRect, fit_crop
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
    if sum(len(stroke.points) for edits in workspace.edits.values() for group in (edits.strokes,*edits.passes) for stroke in group) > 200000 or any(len(edits.passes)>100 for edits in workspace.edits.values()):
        raise SessionError("session_too_large")
    if any((edits.pass_models and len(edits.pass_models)!=len(edits.passes)) or any(model not in MODELS for model in edits.models_for_passes) for edits in workspace.edits.values()):
        raise SessionError("session_invalid")
    def encode_edits(edits):
        result=asdict(edits)
        if edits.logo:
            result['logo']['path']=relative(Path(edits.logo.path))
        return result
    document = {
        'format': 'PhotoPrep', 'version': 5 if any(edits.logo for edits in workspace.edits.values()) else 4 if any(any(model!='lama' for model in edits.models_for_passes) for edits in workspace.edits.values()) else 3 if any(edits.passes for edits in workspace.edits.values()) else 2,
        'output_size': [workspace.output_width, workspace.output_height],
        'selected': relative(workspace.selected) if workspace.selected else None,
        'photos': [{'path': relative(photo.path),
                    'view': asdict(workspace.views.get(photo.path, ViewState())),
                    'edits': encode_edits(workspace.edits.get(photo.path, PhotoEdits()))}
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


def _edits(value) -> PhotoEdits:
    if value is None:
        return PhotoEdits()
    if not isinstance(value,dict) or not isinstance(value.get('strokes',[]),list):
        raise SessionError('session_invalid')
    strokes = []
    count = 0
    try:
        for stroke in value.get('strokes',[]):
            points = stroke['points']
            width = float(stroke['width'])
            if not isinstance(points,list) or not points or not math.isfinite(width) or not 0 < width <= 512:
                raise ValueError()
            count += len(points)
            if count > 200000:
                raise SessionError('session_too_large')
            parsed = []
            for point in points:
                if not isinstance(point,list) or len(point)!=2:
                    raise ValueError()
                x,y = float(point[0]),float(point[1])
                if not all(math.isfinite(v) and abs(v)<=1_000_000 for v in (x,y)):
                    raise ValueError()
                parsed.append((x,y))
            if not isinstance(stroke.get('erase',False),bool):
                raise ValueError()
            strokes.append(MaskStroke(tuple(parsed),width,stroke.get('erase',False)))
        crop_value = value.get('crop')
        crop = None
        if crop_value is not None:
            crop = CropRect(*(float(crop_value[k]) for k in ('x','y','width','height')))
            if (not all(math.isfinite(v) for v in (crop.x,crop.y,crop.width,crop.height))
                or crop.x<0 or crop.y<0 or crop.width<=0 or crop.height<=0
                or crop.x+crop.width>1.000001 or crop.y+crop.height>1.000001):
                raise ValueError()
        passes_value = value.get('passes',[])
        if not isinstance(passes_value,list) or len(passes_value)>100:
            raise ValueError()
        passes = tuple(_edits({'strokes':group}).strokes for group in passes_value)
        if any(not group for group in passes):
            raise ValueError()
        if count + sum(len(stroke.points) for group in passes for stroke in group)>200000:
            raise SessionError('session_too_large')
        pass_models = value.get('pass_models',[])
        if not isinstance(pass_models,list) or (pass_models and len(pass_models)!=len(passes)):
            raise ValueError()
        if any(not isinstance(model,str) or model not in MODELS for model in pass_models):
            raise ValueError()
        logo=None
        if value.get('logo') is not None:
            item=value['logo']
            if not isinstance(item,dict) or not isinstance(item.get('path'),str) or not item['path'] or len(item['path'])>4096:
                raise ValueError()
            width,opacity,x,y=(float(item.get(key,default)) for key,default in (('width',.15),('opacity',1),('x',1),('y',1)))
            if not all(math.isfinite(v) for v in (width,opacity,x,y)) or not .01<=width<=.94 or not 0<=opacity<=1 or not 0<=x<=1 or not 0<=y<=1 or not isinstance(item.get('enabled',True),bool):
                raise ValueError()
            logo=LogoPlacement(item['path'],width,opacity,x,y,item.get('enabled',True))
        return PhotoEdits(tuple(strokes),crop,passes,tuple(pass_models),logo)
    except SessionError:
        raise
    except (TypeError,ValueError,KeyError,OverflowError) as exc:
        raise SessionError('session_invalid') from exc


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
            or type(document.get('version')) is not int or document['version'] not in (1,2,3,4,5)
            or not isinstance(document.get('photos'), list)):
        raise SessionError('session_invalid')
    if len(document['photos']) > MAX_PHOTOS:
        raise SessionError('session_too_large')
    output_size = document.get('output_size', [1136,710]) if document['version'] >= 2 else [1136,710]
    if not isinstance(output_size,list) or len(output_size)!=2 or any(type(v) is not int or not 128<=v<=16000 for v in output_size):
        raise SessionError('session_invalid')
    workspace = Workspace(output_width=output_size[0],output_height=output_size[1])
    point_count = 0
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
        edits = _edits(entry.get('edits')) if document['version']>=2 else PhotoEdits()
        point_count += sum(len(stroke.points) for group in (edits.strokes,*edits.passes) for stroke in group)
        if point_count > 200000:
            raise SessionError('session_too_large')
        if edits.crop is not None:
            edits = replace(edits,crop=fit_crop(photo.width,photo.height,workspace.output_width/workspace.output_height,edits.crop))
        if edits.logo:
            edits=replace(edits,logo=replace(edits.logo,path=str((path.parent/edits.logo.path).resolve())))
        workspace.edits[photo.path] = edits
    selected = document.get('selected')
    try:
        selected_path = (path.parent / selected).resolve() if isinstance(selected, str) else None
    except (OSError, ValueError, RuntimeError):
        selected_path = None
    workspace.selected = selected_path if selected_path in known else (workspace.photos[0].path if workspace.photos else None)
    workspace.mark_saved()
    return workspace, skipped
