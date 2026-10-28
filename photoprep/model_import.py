"""Connect only verified catalogue weights from disk; never execute model code."""
from pathlib import Path
import errno,hashlib,os,shutil


def _hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def local_files(source,spec):
    source=Path(source).expanduser()
    required=spec.files or ((spec.filename,spec.size,spec.sha256),)
    files=[]
    try:
        for name,size,sha in required:
            # Hugging Face snapshots may contain symlinks to their blob cache.
            # Resolve them read-only; only pinned, hashed bytes are ever accepted.
            path=(source/name if spec.files else source).resolve(strict=True)
            if not path.is_file() or path.stat().st_size!=size or _hash(path)!=sha:
                raise ValueError('model_incompatible')
            files.append((name,path,size,sha))
    except (OSError,RuntimeError) as exc:raise ValueError('model_incompatible') from exc
    return files


def install_local(source,target,spec,progress):
    from .diagnostics import event,error
    from .inference import model_lock,model_verified
    from .sdxl_store import safe_file
    target=Path(target)
    progress('verifying',0);files=local_files(source,spec)
    event('model_import_verified',model=spec.id,files=len(files),bytes=spec.size)
    if model_verified(target,spec.id):return
    stage=target.with_name(target.name+f'.{os.getpid()}.part')
    with model_lock(target):
        if stage.exists():raise ValueError('model_busy')
        try:
            stage.mkdir(mode=0o700)
            for index,(name,path,size,sha) in enumerate(files,1):
                staged=safe_file(stage,name);staged.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(path,staged)
                except OSError as exc:
                    if exc.errno not in (errno.EXDEV,errno.EPERM,errno.EACCES,errno.ENOTSUP):raise
                    if shutil.disk_usage(stage).free<size+128*1024*1024:raise ValueError('model_disk_space')
                    shutil.copyfile(path,staged)
                if staged.stat().st_size!=size or _hash(staged)!=sha:raise ValueError('model_incompatible')
                progress('installing',round(index*100/len(files)))
            if spec.files:
                target.mkdir(mode=0o700,exist_ok=True)
                for name,_,_,_ in files:
                    destination=safe_file(target,name);destination.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(stage/name,destination)
            else:os.replace(stage/spec.filename,target)
            event('model_import_finished',model=spec.id,files=len(files))
        except Exception as exc:
            error('model_import_failed',exc,model=spec.id);raise
        finally:shutil.rmtree(stage,ignore_errors=True)


def cached_sources(spec):
    """Known user-selected locations and the exact official Hub cache, no disk scan."""
    from .settings import Preferences
    candidates=[]
    chosen=Preferences().model_source(spec.id)
    if chosen:candidates.append(Path(chosen).expanduser())
    if spec.files:
        home=Path(os.environ.get('HF_HOME',Path.home()/'.cache'/'huggingface'))
        hub=Path(os.environ.get('HF_HUB_CACHE',os.environ.get('HUGGINGFACE_HUB_CACHE',home/'hub')))
        candidates.append(hub/('models--'+spec.repository.replace('/','--'))/'snapshots'/spec.revision)
    return list(dict.fromkeys(path for path in candidates if path.exists()))
