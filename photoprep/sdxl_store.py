"""Pinned multifile weights; downloads never send credentials or image data."""
from pathlib import Path
import hashlib,os,shutil,ssl,urllib.request,urllib.error,time,http.client


def safe_file(root,name):
    root=Path(root)
    if root.is_symlink():raise ValueError('model_integrity_error')
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('model_integrity_error')
    path=root/relative
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p==root or root in p.parents):
        raise ValueError('model_integrity_error')
    return path


def present(root,spec):
    try:
        return all(safe_file(root,name).is_file() and safe_file(root,name).stat().st_size==size for name,size,_ in spec.files)
    except (OSError,ValueError):return False


def verified(root,spec):
    if not present(root,spec):return False
    try:
        for name,size,sha in spec.files:
            digest=hashlib.sha256()
            with safe_file(root,name).open('rb') as stream:
                for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=sha:return False
        return True
    except (OSError,ValueError):return False


def disk_bytes(root,spec):
    total=0
    for name,_,_ in spec.files:
        try:
            path=safe_file(root,name)
            if path.is_file():total+=path.stat().st_size
        except (OSError,ValueError):pass
    return total


def download(root,spec,emit,certifi):
    root=Path(root)
    if root.is_symlink() or (root.exists() and not root.is_dir()):raise ValueError('model_integrity_error')
    stage=root.with_name(root.name+f'.{os.getpid()}.part')
    if stage.exists():raise ValueError('model_busy')
    if shutil.disk_usage(root.parent).free<spec.size+256*1024*1024:raise ValueError('model_disk_space')
    from .diagnostics import event,error
    event('model_download_started',model=spec.id,bytes=spec.size,revision=spec.revision)
    stage.mkdir(mode=0o700)
    received=0
    try:
        for name,size,sha in spec.files:
            event('model_file_download_started',model=spec.id,file=name)
            path=safe_file(stage,name);path.parent.mkdir(parents=True,exist_ok=True)
            count=0
            for attempt in range(3):
                offset=path.stat().st_size if path.exists() else 0
                if offset==size:count=size;break
                url=f'https://huggingface.co/{spec.repository}/resolve/{spec.revision}/{name}?download=true'
                if attempt:url+=f'&retry={int(time.time())}'
                request=urllib.request.Request(url,headers={'User-Agent':'PhotoPrep-model-download','Cache-Control':'no-cache'})
                if offset:request.add_header('Range',f'bytes={offset}-')
                try:
                    with urllib.request.urlopen(request,timeout=60,context=ssl.create_default_context(cafile=certifi.where())) as response:
                        if not response.url.startswith('https://'):raise ValueError('model_download_error')
                        status=getattr(response,'status',200)
                        if offset and status==206:
                            if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('model_integrity_error')
                            mode='ab';count=offset
                        else:mode='wb';count=0
                        with path.open(mode) as output:
                            for chunk in iter(lambda:response.read(1024*1024),b''):
                                count+=len(chunk)
                                if count>size:raise ValueError('model_integrity_error')
                                output.write(chunk)
                                emit('downloading',round((received+count)*100/spec.size))
                            output.flush();os.fsync(output.fileno())
                    if count!=size:raise OSError('incomplete model download')
                    break
                except (OSError,http.client.HTTPException) as exc:
                    if isinstance(exc,urllib.error.HTTPError) and exc.code not in (403,408,429,500,502,503,504):raise
                    if attempt==2:raise
                    error('model_file_download_retry',exc,model=spec.id,file=name,attempt=attempt+1,received=path.stat().st_size if path.exists() else 0)
                    time.sleep(min(2**attempt,4))
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
            if count!=size or digest.hexdigest()!=sha:raise ValueError('model_integrity_error')
            received+=count
            event('model_file_verified',model=spec.id,file=name,bytes=count)
        # All new files are verified before committing anything. Each replacement
        # is atomic; valid old files have the same pinned content as the new files.
        root.mkdir(mode=0o700,exist_ok=True)
        for name,_,_ in spec.files:
            target=safe_file(root,name);target.parent.mkdir(parents=True,exist_ok=True)
            os.replace(stage/name,target)
        event('model_download_finished',model=spec.id,bytes=received)
    except Exception as exc:
        error('model_download_failed',exc,model=spec.id,file=name if 'name' in locals() else None)
        raise
    finally:
        shutil.rmtree(stage,ignore_errors=True)


def delete(root,spec):
    root=Path(root)
    if root.is_symlink():raise ValueError('model_integrity_error')
    if not root.exists():return
    for name,_,_ in spec.files:safe_file(root,name).unlink(missing_ok=True)
    # Leave unrelated files untouched, including files added by the user.
    for directory in sorted({(root/name).parent for name,_,_ in spec.files},key=lambda p:len(p.parts),reverse=True):
        try:directory.rmdir()
        except OSError:pass
    try:root.rmdir()
    except OSError:pass
