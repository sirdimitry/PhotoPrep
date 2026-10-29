"""Private, bounded local diagnostics. No GUI access and no remote transport."""
from __future__ import annotations
import datetime,json,os,re,sys,traceback
from urllib.parse import urlsplit,urlunsplit
from pathlib import Path

MAX_BYTES=10*1024*1024
_path=None
_installed=False
_fault_stream=None


def log_path():
    global _path
    if _path is None:
        if getattr(sys,'frozen',False):
            from PySide6.QtCore import QStandardPaths
            root=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        else:root=Path(__file__).resolve().parents[1]/'work'
        _path=root/'logs'/'photoprep.log'
    return _path


def safe_text(value):
    text=str(value).replace(str(Path.home()),'~')
    def clean_url(match):
        try:
            parts=urlsplit(match.group(0));host=parts.hostname or ''
            if parts.port:host+=':'+str(parts.port)
            return urlunsplit((parts.scheme,host,parts.path,'',''))
        except ValueError:return '[url redacted]'
    text=re.sub(r'https?://[^\s\"<>]+',clean_url,text)
    text=re.sub(r'(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*','Bearer [redacted]',text)
    text=re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|(?:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*)[^\s,;]+',r'\1[redacted]',text)
    text=re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})\b','[redacted]',text)
    return text[:20000]


def _safe(value,key='',depth=0):
    if any(part in key.lower() for part in ('token','secret','password','authorization','cookie')):return '[redacted]'
    if depth>3:return '[truncated]'
    if isinstance(value,dict):return {str(k):_safe(v,str(k),depth+1) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_safe(v,depth=depth+1) for v in value[:20]]
    if isinstance(value,(int,float,bool)) or value is None:return value
    return safe_text(value)


def event(name,**fields):
    try:
        import fcntl
        path=log_path();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.is_symlink() or path.with_suffix('.lock').is_symlink():return
        record={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds'),'pid':os.getpid(),'event':name,**_safe(fields)}
        payload=(json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
        if len(payload)>MAX_BYTES//2:
            record={'time':record['time'],'pid':record['pid'],'event':name,'detail':'entry too large; omitted'}
            payload=(json.dumps(record)+'\n').encode()
        with os.fdopen(os.open(path.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600),'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                fd=os.open(path,os.O_CREAT|os.O_WRONLY|os.O_APPEND|getattr(os,'O_NOFOLLOW',0),0o600)
                with os.fdopen(fd,'ab') as stream:
                    os.chmod(path,0o600)
                    if os.fstat(stream.fileno()).st_size+len(payload)>MAX_BYTES:stream.truncate(0)
                    stream.write(payload)
            finally:fcntl.flock(lock,fcntl.LOCK_UN)
    except Exception:
        # A full/unwritable log must never break processing or shutdown.
        pass


def error(name,exc,**fields):
    event(name,error_type=type(exc).__name__,detail=safe_text(exc),traceback=safe_text(''.join(traceback.format_exception(type(exc),exc,exc.__traceback__))),**fields)


def install():
    global _installed,_fault_stream
    if _installed:return
    _installed=True
    original=sys.excepthook
    def uncaught(kind,value,tb):
        error('uncaught_exception',value)
        original(kind,value,tb)
    sys.excepthook=uncaught
    import threading
    original_thread=threading.excepthook
    def thread_failed(args):
        error('thread_exception',args.exc_value)
        original_thread(args)
    threading.excepthook=thread_failed
    event('diagnostics_ready')
    if os.environ.get('PHOTOPREP_TEST_CRASH_GUARD'):return
    try:
        import faulthandler
        _fault_stream=os.fdopen(os.open(log_path(),os.O_CREAT|os.O_WRONLY|os.O_APPEND|getattr(os,'O_NOFOLLOW',0),0o600),'a',encoding='utf-8')
        faulthandler.enable(file=_fault_stream,all_threads=True)
    except (OSError,RuntimeError):pass
