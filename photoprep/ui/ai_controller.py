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

from ..inference import MODEL_SIZE, model_path, storage_root


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
        self._redownload = False

    @property
    def busy(self):
        return self.process is not None

    def start(self,source,mask,context,*,base_image=None,replay=()):
        if self.busy:
            return
        try:
            cache = storage_root()/'work'/'ai-jobs'
            cache.mkdir(parents=True,exist_ok=True)
            self._directory = Path(tempfile.mkdtemp(prefix='job-',dir=cache))
            self._context = context
            if mask is not None and not mask.save(str(self._directory/'mask.png'),'PNG'):
                self._cleanup()
                self.failed.emit('inference_output_error')
                return
            if base_image is not None:
                source = self._directory/'base.png'
                if not base_image.save(str(source),'PNG'):
                    raise OSError('Could not stage base preview')
            request = {'source':str(source),'model':str(model_path()),
                       'mask':str(self._directory/'mask.png') if mask is not None else None,
                       'replay':[[asdict(stroke) for stroke in group] for group in replay],
                       'output':str(self._directory/'result.png')}
            path = self._directory/'request.json'
            path.write_text(json.dumps(request))
            self._pending = path
            model = model_path()
            # Full SHA256 verification takes place in the worker before every inference.
            if self._redownload or not model.is_file() or model.stat().st_size!=MODEL_SIZE or model.is_symlink():
                self._launch('download',model)
            else:
                self._launch('inpaint',path)
        except OSError:
            self._cleanup()
            self.failed.emit('inference_output_error')
            self.changed.emit()

    def _launch(self,command,path):
        self._command = command
        self._buffer = b''
        self._error = None
        self._cancelled = False
        process = QProcess(self)
        self.process = process
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(lambda:process.readAllStandardError())
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        arguments = ['--photoprep-worker',command,str(path)]
        if not getattr(sys,'frozen',False):
            arguments = ['-m','photoprep',*arguments]
        process.setProgram(sys.executable)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(storage_root()))
        self.progress.emit('downloading' if command=='download' else 'processing',0)
        self.changed.emit()
        process.start()

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
        process,self.process = self.process,None
        process.deleteLater()
        if self._cancelled:
            self._cleanup()
            self.cancelled.emit()
            self.changed.emit()
            return
        if code==0 and status==QProcess.ExitStatus.NormalExit and self._command=='download':
            self._redownload = False
            self._launch('inpaint',self._pending)
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
            self._redownload = error=="model_integrity_error"
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
        if self._directory:
            shutil.rmtree(self._directory,ignore_errors=True)
            self._directory = None
        if self._command=='download':
            model_path().with_suffix('.onnx.part').unlink(missing_ok=True)
        self._pending = None
        self._context = None
