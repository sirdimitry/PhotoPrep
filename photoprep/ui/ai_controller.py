"""Cancellable child processes keep model downloads and inference off the GUI."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtGui import QImage

from ..diagnostics import event,error as log_error
from ..catalog import DEFAULT_MODEL, get_model
from ..inference import model_path, storage_root, cleanup_download, model_present


class AIController(QObject):
    changed = Signal()
    progress = Signal(str,int)
    completed = Signal(object,object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process = None
        self._directory = None
        self._buffer = b''
        self._error = None
        self._cancelled = False
        self._context = None
        self._command = None
        self._pending = None
        self._redownload = set()
        self._downloads = []
        self._download_id = None
        self._failed_model = None
        self._child_pid = 0

    @property
    def busy(self):
        return self.process is not None

    def start(self,source,mask,context,*,base_image=None,replay=(),model_id=DEFAULT_MODEL,replay_models=()):
        if self.busy:
            return
        try:
            get_model(model_id)
            replay_models = replay_models or (DEFAULT_MODEL,)*len(replay)
            if len(replay_models)!=len(replay):
                raise ValueError('unknown_model')
            required = tuple(dict.fromkeys((*replay_models,*((model_id,) if mask is not None else ()))))
            for item in required:
                get_model(item)
            cache = storage_root()/'work'/'ai-jobs'
            cache.mkdir(parents=True,exist_ok=True)
            self._directory = Path(tempfile.mkdtemp(prefix='job-',dir=cache))
            self._context = context
            if mask is not None and not mask.save(str(self._directory/'mask.png'),'PNG'):
                raise OSError('Could not stage mask')
            if base_image is not None:
                source = self._directory/'base.png'
                if not base_image.save(str(source),'PNG'):
                    raise OSError('Could not stage base preview')
            request = {'source':str(source),'model_id':model_id,
                       'model_paths':{item:str(model_path(item)) for item in required},
                       'mask':str(self._directory/'mask.png') if mask is not None else None,
                       'replay':[[asdict(stroke) for stroke in group] for group in replay],
                       'replay_models':list(replay_models),'output':str(self._directory/'result.png')}
            path = self._directory/'request.json'
            path.write_text(json.dumps(request))
            self._pending = path
            self._downloads = []
            for item in required:
                model = model_path(item)
                if item in self._redownload or not model_present(model,item):
                    self._downloads.append(item)
            self._next()
        except (OSError,ValueError) as exc:
            log_error('inference_job_start_failed',exc,model=model_id)
            self._cleanup()
            self.failed.emit('unknown_model' if isinstance(exc,ValueError) else 'inference_output_error')
            self.changed.emit()

    def _next(self):
        if self._downloads:
            self._download_id = self._downloads.pop(0)
            path = self._directory/'download.json'
            path.write_text(json.dumps({'action':'download','model_id':self._download_id,'directory':str(model_path(self._download_id).parent),'force':False}))
            self._launch('download',path)
        else:
            self._download_id = None
            self._launch('inpaint',self._pending)

    def _launch(self,command,path):
        self._command = command
        self._buffer = b''
        self._error = None
        self._failed_model = None
        self._child_pid = 0
        self._cancelled = False
        process = QProcess(self)
        self.process = process
        process.started.connect(lambda:setattr(self,'_child_pid',process.processId()))
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(self._stderr)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        arguments = ['--photoprep-worker','catalog' if command=='download' else command,str(path)]
        if not getattr(sys,'frozen',False):
            arguments = ['-m','photoprep',*arguments]
        process.setProgram(sys.executable)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(storage_root()))
        self.progress.emit('downloading' if command=='download' else 'processing',0)
        self.changed.emit()
        process.start()

    def _stderr(self):
        if self.process:
            text=bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace')
            if text.strip():event('child_stderr',component=type(self).__name__,detail=text[-16000:])

    def _read(self):
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line,self._buffer = self._buffer.split(b'\n',1)
            if self._cancelled:
                continue
            try:
                data = json.loads(line)
                if 'error' in data:
                    self._error = data['error']
                    self._failed_model = data.get('model_id',self._failed_model)
                elif 'stage' in data:
                    self.progress.emit(data['stage'],data.get('percent',0))
            except (ValueError,TypeError):
                continue

    def _process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self._finished(1,QProcess.ExitStatus.CrashExit)

    def _finished(self,code,status):
        if self.process is None:
            return
        self._read()
        event('child_finished',component=type(self).__name__,status=code,exit_status=str(status),error=self._error)
        process,self.process = self.process,None
        process.deleteLater()
        if self._cancelled:
            self._cleanup()
            self.cancelled.emit()
            self.changed.emit()
            return
        if code==0 and status==QProcess.ExitStatus.NormalExit and self._command=='download':
            self._redownload.discard(self._download_id)
            self._next()
            return
        if code==0 and status==QProcess.ExitStatus.NormalExit:
            image = QImage(str(self._directory/'result.png'))
            context = self._context
            self._cleanup()
            if image.isNull():
                self.failed.emit('inference_output_error')
            else:
                self.completed.emit(context,image)
        else:
            error = self._error or ('model_download_error' if self._command=='download' else 'inference_error')
            if error=='model_integrity_error':
                self._redownload.add(self._failed_model or self._download_id or DEFAULT_MODEL)
            self._cleanup()
            self.failed.emit(error)
        self.changed.emit()

    def cancel(self):
        if self.process:
            self._cancelled = True
            self.process.kill()

    def shutdown(self):
        if self.process:
            self.cancel()
            self.process.waitForFinished(3000)
        if self.process is None:
            self._cleanup()

    def _cleanup(self):
        if self._command=='download' and self._download_id:
            cleanup_download(model_path(self._download_id),self._child_pid)
        if self._directory:
            shutil.rmtree(self._directory,ignore_errors=True)
            self._directory = None
        self._pending = None
        self._context = None
        self._downloads = []
