"""Compact model catalogue; file operations run in isolated child processes."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QProcess, QTimer, Signal
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFrame,QLabel,
    QRadioButton,QButtonGroup,QPushButton,QProgressBar)

from ..catalog import MODELS, DEFAULT_MODEL
from ..inference import storage_root, model_path, cleanup_download
from ..i18n import tr


class ModelManager(QWidget):
    changed = Signal()

    def __init__(self,settings,parent=None):
        super().__init__(parent)
        self.language = settings.language
        self.process = None
        self._directory = None
        self._buffer = b''
        self._pid = 0
        self._cancelled = False
        self._action = None
        self._model_id = None
        self._error = None
        self._states = {}
        self._initialized = False
        self._status_key = 'models_hint'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,10,8,8)
        layout.setSpacing(12)
        self.heading = QLabel()
        self.heading.setObjectName('SectionTitle')
        layout.addWidget(self.heading)
        self.choices = QButtonGroup(self)
        self.cards = {}
        for model_id,spec in MODELS.items():
            frame = QFrame()
            frame.setObjectName('SettingsCard')
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(14,12,14,12)
            inner.setSpacing(8)
            choice = QRadioButton(spec.name)
            choice.setStyleSheet('background:transparent;font-weight:650')
            choice.setChecked(model_id==settings.model_id)
            self.choices.addButton(choice)
            inner.addWidget(choice)
            description,status = QLabel(),QLabel()
            description.setWordWrap(True)
            description.setObjectName('Muted')
            status.setObjectName('SmallHint')
            status.setWordWrap(True)
            inner.addWidget(description)
            inner.addWidget(status)
            row = QHBoxLayout()
            buttons = {}
            for action in ('download','verify','delete'):
                button = QPushButton()
                button.setProperty('compact',True)
                button.setFixedHeight(28)
                button.clicked.connect(lambda checked=False,a=action,m=model_id:self.run(a,m))
                row.addWidget(button)
                buttons[action] = button
            inner.addLayout(row)
            layout.addWidget(frame)
            self.cards[model_id] = {'choice':choice,'description':description,'status':status,**buttons}
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setFixedHeight(16)
        self.progress.hide()
        row.addWidget(self.progress,stretch=1)
        self.cancel_button = QPushButton()
        self.cancel_button.setProperty('compact',True)
        self.cancel_button.setFixedHeight(28)
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName('SmallHint')
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.retranslate(settings.language)

    @property
    def busy(self):
        return self.process is not None

    @property
    def selected_model(self):
        return next((key for key,card in self.cards.items() if card['choice'].isChecked()),DEFAULT_MODEL)

    def showEvent(self,event):
        super().showEvent(event)
        if not self._initialized:
            QTimer.singleShot(0,self._inspect_visible)

    def _inspect_visible(self):
        if self.isVisible() and not self._initialized:
            self._initialized = True
            self.run('inspect')

    def retranslate(self,language):
        self.language = language
        self.heading.setText(tr(language,'models_heading'))
        self.cancel_button.setText(tr(language,'ai_cancel'))
        for model_id,spec in MODELS.items():
            card = self.cards[model_id]
            state = self._states.get(model_id,{'state':'unknown','bytes':0})
            installed = state['state']!='absent' and state['state']!='unknown'
            card['description'].setText(tr(language,'model_'+model_id+'_description'))
            card['status'].setText(tr(language,'model_size_state',size=f'{spec.size/1e6:.1f}',disk=f'{state["bytes"]/1e6:.1f}',state=tr(language,'model_'+state['state']),license=spec.license))
            for action in ('download','verify','delete'):
                card[action].setText(tr(language,'model_reinstall' if action=='download' and installed else 'model_'+action))
                card[action].setEnabled(not self.busy and (action=='download' or installed))
        self.status.setText(tr(language,self._status_key))

    def run(self,action,model_id=None):
        if self.busy:
            return
        if model_id is not None and model_id not in MODELS:
            return
        try:
            cache = storage_root()/'work'/'model-jobs'
            cache.mkdir(parents=True,exist_ok=True)
            self._directory = Path(tempfile.mkdtemp(prefix='catalog-',dir=cache))
            path = self._directory/'request.json'
            path.write_text(json.dumps({'action':action,'model_id':model_id,'directory':str(model_path(DEFAULT_MODEL).parent),'force':action=='download'}))
            self._action,self._model_id = action,model_id
            self._buffer,self._pid,self._error,self._cancelled = b'',0,None,False
            process = QProcess(self)
            self.process = process
            process.started.connect(lambda:setattr(self,'_pid',process.processId()))
            process.readyReadStandardOutput.connect(self._read)
            process.readyReadStandardError.connect(lambda:process.readAllStandardError())
            process.finished.connect(self._finished)
            process.errorOccurred.connect(self._process_error)
            args = ['--photoprep-worker','catalog',str(path)]
            if not getattr(sys,'frozen',False):
                args = ['-m','photoprep',*args]
            process.setProgram(sys.executable)
            process.setArguments(args)
            process.setWorkingDirectory(str(storage_root()))
            self._status_key = 'models_working'
            self.progress.setRange(0,100 if action=='download' else 0)
            self.progress.setValue(0)
            self.progress.show()
            self.cancel_button.show()
            self.retranslate(self.language)
            self.changed.emit()
            process.start()
        except OSError:
            self._status_key = 'models_operation_error'
            self._cleanup()
            self.retranslate(self.language)

    def _read(self):
        if not self.process:
            return
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line,self._buffer = self._buffer.split(b'\n',1)
            if self._cancelled:
                continue
            try:
                data = json.loads(line)
                if 'inventory' in data:
                    self._states = data['inventory']
                if 'error' in data:
                    self._error = data['error']
                if data.get('stage')=='downloading':
                    self.progress.setRange(0,100)
                    self.progress.setValue(data.get('percent',0))
            except (ValueError,TypeError):
                continue

    def _process_error(self,error):
        if error==QProcess.ProcessError.FailedToStart:
            self._finished(1,QProcess.ExitStatus.CrashExit)

    def _finished(self,code,status):
        if not self.process:
            return
        self._read()
        process,self.process = self.process,None
        process.deleteLater()
        if self._cancelled:
            self._status_key = 'models_cancelled'
        elif code==0 and status==QProcess.ExitStatus.NormalExit:
            self._status_key = 'models_hint'
        else:
            self._status_key = self._error if self._error in ('model_busy','model_integrity_error','model_download_error') else 'models_operation_error'
        self._cleanup()
        self.progress.hide()
        self.cancel_button.hide()
        self.retranslate(self.language)
        self.changed.emit()

    def cancel(self):
        if self.process:
            self._cancelled = True
            self.process.kill()

    def shutdown(self):
        if self.process:
            self.cancel()
            self.process.waitForFinished(3000)
        if not self.process:
            self._cleanup()

    def _cleanup(self):
        if self._action=='download' and self._model_id:
            cleanup_download(model_path(self._model_id),self._pid)
        if self._directory:
            shutil.rmtree(self._directory,ignore_errors=True)
            self._directory = None
