"""Pinned local LaMa model and isolated, mask-only inference. No photo uploads."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import ssl
import urllib.request
from contextlib import contextmanager

from .catalog import DEFAULT_MODEL, MODELS, get_model

MODEL_REVISION = 'c3c0c9e468934d62e79c329e35d82dd09ff8c444'
MODEL_NAME = 'lama_fp32.onnx'
MODEL_SIZE = 208044816
MODEL_SHA256 = '1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6'
MODEL_URL = f'https://huggingface.co/Carve/LaMa-ONNX/resolve/{MODEL_REVISION}/{MODEL_NAME}'


def storage_root():
    if not getattr(sys, 'frozen', False):
        return Path(__file__).resolve().parents[1]
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))


def model_path(model_id=DEFAULT_MODEL):
    return storage_root() / 'models' / get_model(model_id).filename


def model_verified(path,model_id=DEFAULT_MODEL):
    spec = get_model(model_id)
    path = Path(path)
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size != spec.size:
            return False
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024), b''):
                digest.update(chunk)
        return digest.hexdigest() == spec.sha256
    except OSError:
        return False


def progress(stage, percent=0):
    print(json.dumps({'stage':stage, 'percent':percent}), flush=True)


def download_model(target,model_id=DEFAULT_MODEL,*,force=False):
    """Only retrieve the pinned public model; no tokens, cookies or user data."""
    import certifi
    spec = get_model(model_id)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not force and model_verified(target,model_id):
        return
    with model_lock(target):
        _download_locked(target,spec,certifi)


def _download_locked(target,spec,certifi):
    partial = target.with_name(target.name+f'.{os.getpid()}.part')
    partial.unlink(missing_ok=True)
    digest, received = hashlib.sha256(), 0
    try:
        request = urllib.request.Request(spec.url, headers={'User-Agent':'PhotoPrep-model-download'})
        with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response, partial.open('xb') as stream:
            if not response.url.startswith('https://'):
                raise ValueError('model_download_error')
            for chunk in iter(lambda:response.read(1024*1024), b''):
                received += len(chunk)
                if received > spec.size:
                    raise ValueError('model_integrity_error')
                stream.write(chunk)
                digest.update(chunk)
                progress('downloading', round(received*100/spec.size))
        if received != spec.size or digest.hexdigest() != spec.sha256:
            raise ValueError('model_integrity_error')
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def image_array(image):
    import numpy as np
    from PySide6.QtGui import QImage
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(),image.bytesPerLine())
    return data[:,:image.width()*4].reshape(image.height(),image.width(),4).copy()


def array_image(array):
    from PySide6.QtGui import QImage
    array = array.copy(order='C')
    return QImage(array.data,array.shape[1],array.shape[0],array.strides[0],QImage.Format.Format_RGBA8888).copy()


def mask_array(mask):
    import numpy as np
    from PySide6.QtGui import QImage
    gray = mask.convertToFormat(QImage.Format.Format_Grayscale8)
    return np.frombuffer(gray.constBits(),dtype=np.uint8).reshape(gray.height(),gray.bytesPerLine())[:,:gray.width()].copy()


def context_rect(mask):
    """Square context around all selected pixels, clipped to the source bounds."""
    import numpy as np
    ys,xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError('empty_mask')
    height,width = mask.shape
    span = max(int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1))
    side = max(256,span+max(64,span//2))
    center_x,center_y = (int(xs.min())+int(xs.max()))/2,(int(ys.min())+int(ys.max()))/2
    cw,ch = min(side,width),min(side,height)
    x = max(0,min(width-cw,round(center_x-cw/2)))
    y = max(0,min(height-ch,round(center_y-ch/2)))
    return x,y,cw,ch


def inpaint(source, mask, predict):
    """Run 512px context inference; preserve every unmasked RGBA pixel exactly."""
    import numpy as np
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    if source.isNull() or mask.size()!=source.size():
        raise ValueError('inference_image_error')
    if source.width()*source.height()>40_000_000:
        raise ValueError('inference_image_large')
    original = image_array(source)
    coverage = mask_array(mask)
    x,y,width,height = context_rect(coverage)
    rgb = source.copy(x,y,width,height).scaled(512,512,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    cropped_mask = mask.copy(x,y,width,height).scaled(512,512,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    binary = mask_array(cropped_mask)>0
    # A small inference-only dilation covers soft mask edges. Final compositing
    # still uses the exact original coverage, so no extra pixels are changed.
    padded = np.pad(binary,2)
    binary = np.logical_or.reduce([padded[dy:dy+512,dx:dx+512] for dy in range(5) for dx in range(5)])
    image_input = np.transpose(image_array(rgb)[:,:,:3].astype(np.float32)/255,(2,0,1))[None]
    mask_input = binary.astype(np.float32)[None,None]
    predicted = np.asarray(predict(image_input,mask_input))
    if predicted.shape!=(1,3,512,512) or not np.isfinite(predicted).all():
        raise ValueError('inference_output_error')
    output = np.clip(predicted[0].transpose(1,2,0),0,255).astype(np.uint8)
    rgba = np.concatenate((output,np.full((512,512,1),255,dtype=np.uint8)),axis=2)
    restored = array_image(rgba).scaled(width,height,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
    fill = image_array(restored)[:,:,:3].astype(np.float32)
    alpha = coverage[y:y+height,x:x+width,None].astype(np.float32)/255
    result = original.copy()
    old = original[y:y+height,x:x+width,:3]
    result[y:y+height,x:x+width,:3] = np.rint(fill*alpha+old*(1-alpha)).astype(np.uint8)
    # Alpha is never changed, including in transparent sources.
    assert np.array_equal(result[coverage==0],original[coverage==0])
    output=array_image(result)
    if source.colorSpace().isValid():output.setColorSpace(source.colorSpace())
    return output


def run_job(request_path):
    from PySide6.QtGui import QImage, QImageReader
    import onnxruntime as ort
    request = json.loads(Path(request_path).read_text())
    active_id = request.get('model_id',DEFAULT_MODEL)
    get_model(active_id)
    replay = request.get('replay',[])
    replay_models = request.get('replay_models') or [DEFAULT_MODEL]*len(replay)
    if len(replay_models)!=len(replay) or len(replay)>100:
        raise ValueError('inference_image_error')
    ids = set(replay_models + ([active_id] if request.get('mask') else []))
    paths = {model_id:Path(request.get('model_paths',{}).get(model_id,request.get('model',model_path(model_id)))) for model_id in ids}
    progress('verifying')
    for model_id,path in paths.items():
        if not model_verified(path,model_id):
            print(json.dumps({'error':'model_integrity_error','model_id':model_id}),flush=True)
            raise ValueError('model_integrity_error')
    reader = QImageReader(request['source'])
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width()*size.height()>40_000_000:
        raise ValueError('inference_image_large')
    source = reader.read()
    progress('processing')
    predictor = create_predictor(paths)
    from .editing import MaskStroke, render_mask
    result = source
    replay = request.get('replay',[])
    if not isinstance(replay,list) or len(replay)>100:
        raise ValueError('inference_image_error')
    for index,group in enumerate(replay):
        strokes = tuple(MaskStroke(tuple(tuple(point) for point in item['points']),item['width'],item.get('erase',False)) for item in group)
        mask = render_mask(result.width(),result.height(),strokes)
        result = inpaint(result,mask,predictor(replay_models[index]))
        progress('processing',round((index+1)*100/(len(replay)+bool(request.get('mask')))))
    if request.get('mask'):
        result = inpaint(result,QImage(request['mask']),predictor(active_id))
    elif not replay:
        raise ValueError('empty_mask')
    if not result.save(request['output'],'PNG'):
        raise ValueError('inference_output_error')
    progress('complete',100)


def worker_main(arguments):
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication(['PhotoPrep worker'])
    app.setOrganizationName('sirdimitry')
    app.setApplicationName('PhotoPrep')
    try:
        command,path = arguments
        if command=='download':
            download_model(path)
        elif command=='catalog':
            catalog_job(path)
        elif command=='export':
            from .exporting import export_job
            export_job(path)
        elif command=='inpaint':
            run_job(path)
        else:
            return 2
        return 0
    except Exception as exc:
        # Return only known user-facing codes; paths and native internals stay local.
        code = str(exc)
        allowed = {'model_download_error','model_integrity_error','empty_mask','inference_image_error',
                   'inference_image_large','inference_output_error','unknown_model','model_busy',
                   'export_failed','export_pending_mask','export_size_large','export_source_changed','logo_invalid'}
        print(json.dumps({'error':code if code in allowed else 'model_download_error' if arguments and arguments[0]=='download' else 'export_failed' if arguments and arguments[0]=='export' else 'inference_error'}),flush=True)
        return 1


@contextmanager
def model_lock(path):
    from PySide6.QtCore import QLockFile
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    lock = QLockFile(str(path)+'.lock')
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise ValueError('model_busy')
    try:
        yield
    finally:
        lock.unlock()


def inventory(directory=None):
    result = {}
    for model_id,spec in MODELS.items():
        path = Path(directory)/spec.filename if directory is not None else model_path(model_id)
        try:
            size = path.stat().st_size if path.is_file() and not path.is_symlink() else 0
        except OSError:
            size = 0
        result[model_id] = {'state':'ready' if model_verified(path,model_id) else 'damaged' if path.exists() else 'absent','bytes':size}
    return result


def catalog_job(request_path):
    request = json.loads(Path(request_path).read_text())
    action = request['action']
    directory = request.get('directory')
    if action!='inspect':
        model_id = request['model_id']
        get_model(model_id)
        path = Path(directory)/get_model(model_id).filename if directory is not None else model_path(model_id)
        if action=='download':
            try:
                download_model(path,model_id,force=request.get('force',False))
            except OSError as exc:
                raise ValueError('model_download_error') from exc
        elif action=='delete':
            with model_lock(path):
                path.unlink(missing_ok=True)
                path.with_suffix('.onnx.part').unlink(missing_ok=True)
                for partial in path.parent.glob(path.name+'.*.part'):
                    if partial.is_file() or partial.is_symlink():
                        partial.unlink()
        elif action=='verify':
            progress('verifying')
        else:
            raise ValueError('unknown_model')
    print(json.dumps({'inventory':inventory(directory)}),flush=True)


def cleanup_download(path,pid):
    if pid:
        path = Path(path)
        try:
            path.with_name(path.name+f'.{pid}.part').unlink(missing_ok=True)
        except OSError:
            pass


def create_predictor(paths):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = min(4,os.cpu_count() or 1)
    options.inter_op_num_threads = 1
    options.add_session_config_entry('session.intra_op.allow_spinning','0')
    options.log_severity_level = 3
    session = None
    session_id = None
    def predictor(model_id):
        nonlocal session,session_id
        if session_id!=model_id:
            session = None  # release the previous model before allocating another
            session = ort.InferenceSession(str(paths[model_id]),sess_options=options,providers=['CPUExecutionProvider'])
            session_id = model_id
        def predict(image,mask):
            if model_id=='migan':
                import numpy as np
                values = {'image':np.rint(image*255).astype(np.uint8),
                          'mask':np.rint((1-mask)*255).astype(np.uint8)}
            else:
                values = {'image':image,'mask':mask}
            return session.run(None,values)[0]
        return predict
    return predictor
