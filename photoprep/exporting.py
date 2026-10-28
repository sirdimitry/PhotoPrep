"""Sequential, atomic JPEG/PNG export from the same crop and retouch plans."""
from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage,QImageReader,QPainter,QColorSpace

from .branding import read_logo,logo_rect
from .catalog import get_model
from .editing import fit_crop,render_mask
from .inference import model_verified,download_model,create_predictor
from .session import load_session

MAX_PIXELS=40_000_000


def emit(**data):
    print(json.dumps(data,ensure_ascii=False),flush=True)


def signature(path):
    stat=Path(path).stat()
    return [stat.st_mtime_ns,stat.st_size]


def check_signature(path,expected):
    try:
        if signature(path)==expected:return
    except OSError:pass
    raise ValueError('export_source_changed')


def compose(image,edits,width,height,logo_image=None):
    if not 128<=width<=16000 or not 128<=height<=16000 or width*height>MAX_PIXELS:
        raise ValueError('export_size_large')
    if image.isNull():raise ValueError('inference_image_error')
    crop=(edits.crop or fit_crop(image.width(),image.height(),width/height)).pixels(image.width(),image.height())
    if abs(crop.width()/crop.height()-width/height)>1e-6:
        raise ValueError('export_failed')
    if image.colorSpace().isValid():
        image=image.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    output=QImage(width,height,QImage.Format.Format_RGBA8888)
    if output.isNull():raise MemoryError('Could not allocate export')
    output.fill(0)
    painter=QPainter(output)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    try:
        painter.drawImage(QRectF(0,0,width,height),image,crop)
        logo=edits.logo
        if logo and logo.enabled and logo.opacity>0:
            asset=logo_image if logo_image is not None else read_logo(logo.path,logo.mode)
            painter.setOpacity(logo.opacity)
            painter.drawImage(logo_rect(QRectF(0,0,width,height),logo,asset),asset)
    finally:
        painter.end()
    return output


def rename_exclusive(source,target):
    """Atomic commit without replacing an existing path, including symlinks."""
    if sys.platform=='darwin':
        library=ctypes.CDLL(None,use_errno=True)
        rename=library.renamex_np
        rename.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint]
        rename.restype=ctypes.c_int
        if rename(os.fsencode(source),os.fsencode(target),0x00000004):  # RENAME_EXCL, macOS SDK sys/stdio.h
            error=ctypes.get_errno()
            if error==errno.EEXIST:raise FileExistsError(error,os.strerror(error),str(target))
            raise OSError(error,os.strerror(error),str(target))
    else:
        os.link(source,target)
        Path(source).unlink()


def save_clean(image,folder,stem,format,quality,protected=(),*,start_index=0):
    from PIL import Image
    if format not in ('JPEG','PNG') or not 1<=quality<=100:
        raise ValueError('export_failed')
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    # Start from new pixel storage. No EXIF, XMP, comments, ICC or source text is copied.
    rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
    clean=Image.frombuffer('RGBA',(rgba.width(),rgba.height()),rgba.constBits(),'raw','RGBA',rgba.bytesPerLine(),1)
    if format=='JPEG':
        background=Image.new('RGB',clean.size,'white')
        background.paste(clean,mask=clean.getchannel('A'))
        clean=background
    suffix='.jpg' if format=='JPEG' else '.png'
    protected={Path(path).resolve() for path in protected}
    partial=None
    try:
        with tempfile.NamedTemporaryFile(prefix=f'.photoprep-{os.getpid()}-',suffix='.tmp',dir=folder,delete=False) as stream:
            partial=Path(stream.name)
            if format=='JPEG':
                clean.save(stream,format='JPEG',quality=quality,optimize=True,progressive=True)
            else:
                clean.save(stream,format='PNG',optimize=True)
            stream.flush();os.fsync(stream.fileno())
        for index in range(start_index,1000000):
            name=f'{stem}-logo'+(f'{index:02d}' if index else '')+suffix
            target=folder/name
            if target.resolve() in protected or target.exists() or target.is_symlink():continue
            try:
                rename_exclusive(partial,target)
                return target
            except FileExistsError:
                continue
        raise ValueError('export_failed')
    finally:
        if partial:partial.unlink(missing_ok=True)


def cleanup_partial(folder,pid):
    if pid and Path(folder).is_dir():
        for path in Path(folder).glob(f'.photoprep-{pid}-*.tmp'):
            try:path.unlink()
            except OSError:pass


def export_job(request_path):
    request=json.loads(Path(request_path).read_text())
    workspace,skipped=load_session(Path(request['session']))
    wanted=set(request['sources'])
    photos=[photo for photo in workspace.photos if str(photo.path) in wanted]
    missing=[path for path in request['sources'] if path not in {str(photo.path) for photo in photos}]
    width,height=workspace.output_width,workspace.output_height
    if width*height>MAX_PIXELS:raise ValueError('export_size_large')
    if request['format'] not in ('JPEG','PNG') or not 1<=request['quality']<=100:raise ValueError('export_failed')
    ids=set()
    protected=[Path(path) for path in request.get("protected",[])] or [photo.path for photo in workspace.photos]
    for photo in photos:
        edits=workspace.edits[photo.path]
        if edits.strokes:raise ValueError('export_pending_mask')
        ids.update(edits.models_for_passes)
        if edits.logo:protected.append(Path(edits.logo.path))
    paths={key:Path(request['models'][key]) for key in ids}
    for key,path in paths.items():
        emit(stage='export_model',name=get_model(key).name)
        if not model_verified(path,key):
            try:download_model(path,key,force=True)
            except OSError as exc:raise ValueError('model_download_error') from exc
    predictor=create_predictor(paths) if ids else None
    completed,errors=0,[]
    asset_key,asset_image=None,None
    for path in missing:
        errors.append({'name':Path(path).name,'error':'export_source_changed'})
        emit(file_error=Path(path).name,error='export_source_changed')
    for index,photo in enumerate(photos,1+len(missing)):
        edits=workspace.edits[photo.path]
        emit(stage='export_photo',index=index,total=len(wanted),name=photo.path.name)
        try:
            check_signature(photo.path,request['sources'][str(photo.path)])
            if photo.width*photo.height>MAX_PIXELS:raise ValueError('inference_image_large')
            reader=QImageReader(str(photo.path));reader.setAutoTransform(True)
            image=reader.read()
            if image.isNull():raise ValueError('inference_image_error')
            for pass_index,(strokes,model_id) in enumerate(zip(edits.passes,edits.models_for_passes),1):
                from .inference import inpaint
                emit(stage='export_retouch',index=index,total=len(wanted),pass_index=pass_index,passes=len(edits.passes),name=photo.path.name)
                image=inpaint(image,render_mask(image.width(),image.height(),strokes),predictor(model_id))
            logo=edits.logo
            if logo and logo.enabled and logo.opacity>0:
                check_signature(logo.path,request['logos'].get(logo.path))
            emit(stage='export_write',index=index,total=len(wanted),name=photo.path.name)
            if logo and logo.enabled and logo.opacity>0:
                key=(logo.path,logo.mode,*request['logos'][logo.path])
                if key!=asset_key:
                    asset_image=read_logo(logo.path,logo.mode);asset_key=key
            image=compose(image,edits,width,height,asset_image if logo and logo.enabled else None)
            check_signature(photo.path,request['sources'][str(photo.path)])
            if logo and logo.enabled and logo.opacity>0:check_signature(logo.path,request['logos'].get(logo.path))
            target=save_clean(image,photo.path.parent,photo.path.stem,request['format'],request['quality'],protected,start_index=index-len(missing) if len(wanted)>1 else 0)
            completed+=1
            emit(file=str(target),completed=completed,index=index,total=len(wanted))
        except Exception as exc:
            if isinstance(exc,OSError) and exc.errno in (errno.ENOSPC,errno.EDQUOT,errno.EROFS,errno.EACCES,errno.EIO):
                raise ValueError("export_failed") from exc
            code=str(exc)
            if code not in ('export_source_changed','logo_invalid','inference_image_large','inference_image_error','model_integrity_error'):
                code='export_failed'
            errors.append({'name':photo.path.name,'error':code})
            emit(file_error=photo.path.name,error=code)
    emit(summary=True,completed=completed,errors=errors,total=len(wanted))
