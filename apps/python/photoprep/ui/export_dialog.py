"""A modal export snapshot with cancellable background processing."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QProcess,QUrl,Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,
    QPushButton,QRadioButton,QButtonGroup,QSlider,QProgressBar,QApplication)

from ..diagnostics import event,error as log_error
from ..catalog import MODELS
from ..exporting import signature,cleanup_partial,MAX_PIXELS
from ..inference import storage_root,model_path,cleanup_download
from ..session import save_session,SessionError
from ..workspace import Workspace
from ..i18n import tr
from .theme import stylesheet


class ExportDialog(QDialog):
    def __init__(self,workspace,settings,parent=None):
        super().__init__(parent)
        self.workspace=workspace
        self.settings=settings
        self.language=settings.language
        self.process=None
        self._directory=None
        self._pid=0
        self._buffer=b''
        self._cancelled=False
        self._error=None
        self._finished_once=False
        self.files=[]
        self.errors=[]
        self._output_folder=None
        self._output_folders=set()
        self._model_name=''
        self.setStyleSheet(stylesheet(settings.appearance))
        self.setWindowTitle(self.t('export'))
        self.setFixedWidth(520)
        root=QVBoxLayout(self);root.setContentsMargins(24,24,24,24);root.setSpacing(16)
        self.dimensions=QLabel(f'{workspace.output_width} × {workspace.output_height} px')
        self.dimensions.setObjectName('SectionTitle');root.addWidget(self.dimensions)
        root.addWidget(QLabel(self.t('export_range')))
        row=QHBoxLayout();self.range_group=QButtonGroup(self)
        self.current=QRadioButton(self.t('export_current'))
        self.all=QRadioButton(self.t('export_all',count=len(workspace.photos)))
        for button in (self.current,self.all):
            self.range_group.addButton(button);row.addWidget(button);button.toggled.connect(self.validate)
        self.all.setChecked(len(workspace.photos)>1)
        self.current.setChecked(len(workspace.photos)<=1)
        root.addLayout(row)
        root.addWidget(QLabel(self.t('export_common_format')))
        row=QHBoxLayout();self.format_group=QButtonGroup(self);self.formats={}
        for name in ('JPEG','PNG'):
            button=QRadioButton(name);button.setChecked(name==settings.export_format)
            self.format_group.addButton(button);self.formats[name]=button;row.addWidget(button)
            button.toggled.connect(self.validate)
        root.addLayout(row)
        row=QHBoxLayout();self.quality_label=QLabel();row.addWidget(self.quality_label)
        self.quality=QSlider(Qt.Orientation.Horizontal);self.quality.setRange(1,100);self.quality.setValue(settings.export_quality)
        self.quality.setMaximumWidth(230);self.quality.valueChanged.connect(self.validate);row.addWidget(self.quality)
        root.addLayout(row)
        self.destination=QLabel(self.t('export_beside_sources'));self.destination.setWordWrap(True);root.addWidget(self.destination)
        self.note=QLabel(self.t('export_note'));self.note.setWordWrap(True);self.note.setObjectName('SmallHint');root.addWidget(self.note)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);self.progress.hide();root.addWidget(self.progress)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);root.addWidget(self.status)
        row=QHBoxLayout()
        self.open_folder=QPushButton(self.t('export_open_folder'));self.open_folder.setProperty('compact',True)
        self.open_folder.clicked.connect(lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_folder))))
        self.open_folder.hide();row.addWidget(self.open_folder);row.addStretch(1)
        self.close_button=QPushButton(self.t('cancel'));self.close_button.clicked.connect(self.cancel_or_close)
        row.addWidget(self.close_button)
        self.start_button=QPushButton(self.t('export_start'));self.start_button.setObjectName('Primary');self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button);root.addLayout(row)
        self._quit_connected=True
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        self.validate()

    def t(self,key,**data):return tr(self.language,key,**data)

    @property
    def busy(self):return self.process is not None

    @property
    def selected_photos(self):
        return self.workspace.photos if self.all.isChecked() else [photo for photo in self.workspace.photos if photo.path==self.workspace.selected]

    def validate(self):
        if not hasattr(self,'start_button'):return
        jpeg=self.formats['JPEG'].isChecked()
        self.quality.setEnabled(jpeg and not self.busy)
        self.quality.setVisible(jpeg);self.quality_label.setVisible(jpeg)
        self.quality_label.setText(self.t('export_quality',quality=self.quality.value()))
        self.start_button.setText(self.t('export_start_all',count=len(self.selected_photos)) if self.all.isChecked() else self.t('export_start'))
        valid=bool(self.selected_photos)
        message=''
        if self.workspace.output_width*self.workspace.output_height>MAX_PIXELS:message='export_size_large'
        elif any(self.workspace.edits[photo.path].strokes for photo in self.selected_photos):message='export_pending_mask'
        elif any(edits.logo and edits.logo.enabled and edits.logo.opacity>0 and not Path(edits.logo.path).is_file() for edits in (self.workspace.edits[photo.path] for photo in self.selected_photos)):message='logo_invalid'
        self.start_button.setEnabled(valid and not message and not self.busy and not self._finished_once)
        if not self.busy and not self._finished_once:self.status.setText(self.t(message) if message else '')

    def start(self):
        if self.busy or not self.start_button.isEnabled():return
        try:
            self._output_folders={photo.path.parent for photo in self.selected_photos}
            self._output_folder=self.selected_photos[0].path.parent
            jobs=storage_root()/'work'/'export-jobs';jobs.mkdir(parents=True,exist_ok=True)
            self._directory=Path(tempfile.mkdtemp(prefix='export-',dir=jobs))
            session=self._directory/'snapshot.photoprep.json'
            selected=self.selected_photos
            snapshot=Workspace(photos=list(selected),selected=self.workspace.selected,views={p.path:self.workspace.views[p.path] for p in selected},edits={p.path:self.workspace.edits[p.path] for p in selected},output_width=self.workspace.output_width,output_height=self.workspace.output_height)
            save_session(session,snapshot)
            sources={}
            for photo in self.selected_photos:
                try:sources[str(photo.path)]=signature(photo.path)
                except OSError:sources[str(photo.path)]=None
            logos={}
            for photo in self.selected_photos:
                logo=self.workspace.edits[photo.path].logo
                if logo and logo.enabled and logo.opacity>0:logos[logo.path]=signature(logo.path)
            format=next(key for key,button in self.formats.items() if button.isChecked())
            self.settings.export_format=format;self.settings.export_quality=self.quality.value()
            request={'session':str(session),'sources':sources,'protected':[str(photo.path) for photo in self.workspace.photos],'logos':logos,'models':{key:str(model_path(key)) for key in MODELS},'format':format,'quality':self.quality.value()}
            path=self._directory/'request.json';path.write_text(json.dumps(request))
            self._pid=0;self._error=None;self._cancelled=False;self.files=[];self.errors=[];self._buffer=b''
            process=QProcess(self);self.process=process
            process.started.connect(lambda:setattr(self,'_pid',process.processId()))
            process.readyReadStandardOutput.connect(self._read)
            process.readyReadStandardError.connect(self._stderr)
            process.finished.connect(self._finished)
            process.errorOccurred.connect(lambda error:self._finished(1,QProcess.ExitStatus.CrashExit) if error==QProcess.ProcessError.FailedToStart else None)
            args=['--photoprep-worker','export',str(path)]
            if not getattr(sys,'frozen',False):args=['-m','photoprep',*args]
            process.setProgram(sys.executable);process.setArguments(args);process.setWorkingDirectory(str(storage_root()))
            for widget in (self.current,self.all,*self.formats.values()):widget.setEnabled(False)
            self.progress.show();self.validate();process.start()
        except (OSError,ValueError) as exc:
            log_error('export_job_start_failed',exc)
            self._error=str(exc) if isinstance(exc,SessionError) else 'export_failed';self._cleanup();self.status.setText(self.t(self._error))

    def _stderr(self):
        if self.process:
            text=bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace')
            if text.strip():event('child_stderr',component=type(self).__name__,detail=text[-16000:])

    def _read(self):
        if not self.process:return
        self._buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line,self._buffer=self._buffer.split(b'\n',1)
            try:
                data=json.loads(line)
                if 'file' in data:
                    self.files.append(data['file'])
                    if len(self.files)==1:self._output_folder=Path(data['file']).parent
                if 'file_error' in data:self.errors.append((data['file_error'],data['error']))
                elif 'error' in data:self._error=data['error']
                if data.get('stage')=='export_model':self._model_name=data['name']
                if data.get('stage')=='downloading':
                    self.status.setText(self.t('ai_downloading',name=self._model_name,percent=data.get('percent',0)))
                elif data.get('stage','').startswith('export_'):
                    self.status.setText(self.t(data['stage'],**{key:value for key,value in data.items() if key!='stage'}))
                if data.get('total') and 'index' in data:self.progress.setValue(round((data['index']-('file' not in data))*100/data['total']))
            except (ValueError,TypeError,KeyError):continue

    def _finished(self,code,status):
        if not self.process:return
        self._read();event('child_finished',component=type(self).__name__,status=code,exit_status=str(status),error=self._error);process,self.process=self.process,None;process.deleteLater();self._finished_once=True
        self._cleanup();self.close_button.setText(self.t('close'));self.open_folder.setVisible(bool(self.files))
        self.progress.setValue(100 if not self._cancelled and code==0 else self.progress.value())
        if self._cancelled:self.status.setText(self.t('export_cancelled',count=len(self.files)))
        elif self._error or code!=0:self.status.setText(self.t(self._error or 'export_failed'))
        elif self.errors:self.status.setText(self.t('export_summary_errors',count=len(self.files),errors=len(self.errors))+'\n'+'\n'.join(name+': '+self.t(error) for name,error in self.errors[:5]))
        else:self.status.setText(self.t('export_done',count=len(self.files)))
        self.validate()

    def cancel_or_close(self):
        if self.process:self._cancelled=True;self.process.kill()
        else:self.accept()

    def _cleanup(self):
        for folder in self._output_folders:cleanup_partial(folder,self._pid)
        for key in MODELS:cleanup_download(model_path(key),self._pid)
        if self._directory:shutil.rmtree(self._directory,ignore_errors=True);self._directory=None

    def _shutdown(self):
        if self.process:
            self._cancelled=True;self.process.kill();self.process.waitForFinished(3000)
        self._cleanup()

    def reject(self):
        self._shutdown();super().reject()

    def done(self,result):
        self._shutdown()
        if self._quit_connected:
            QApplication.instance().aboutToQuit.disconnect(self._shutdown)
            self._quit_connected=False
        super().done(result)
        self.deleteLater()
