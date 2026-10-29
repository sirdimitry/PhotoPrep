import json,os,subprocess,sys
from pathlib import Path
from photoprep import diagnostics


def test_log_rotates_at_limit_without_backups(tmp_path,monkeypatch):
    path=tmp_path/'logs/photoprep.log';monkeypatch.setattr(diagnostics,'_path',path);monkeypatch.setattr(diagnostics,'MAX_BYTES',512)
    for index in range(100):diagnostics.event('rotation',index=index,message='sample diagnostic entry')
    assert path.stat().st_size<=512 and path.stat().st_mode&0o777==0o600
    records=[json.loads(line) for line in path.read_text().splitlines()]
    assert records[-1]['index']==99
    assert {p.name for p in path.parent.iterdir()}=={'photoprep.log','photoprep.lock'}


def test_log_removes_credentials_queries_tokens_and_home_paths(tmp_path,monkeypatch):
    path=tmp_path/'photoprep.log';monkeypatch.setattr(diagnostics,'_path',path)
    diagnostics.event('privacy',token='SECRET_TOKEN',url='https://user:SECRET_PASSWORD@example.com/file?signature=SECRET_QUERY',detail='Authorization: Bearer SECRET_BEARER '+str(Path.home())+'/photo.jpg')
    text=path.read_text()
    assert all(value not in text for value in ('SECRET_TOKEN','SECRET_PASSWORD','SECRET_QUERY','SECRET_BEARER',str(Path.home())))
    assert 'https://example.com/file' in text


def test_multiple_processes_append_valid_records(tmp_path,monkeypatch):
    path=tmp_path/'photoprep.log'
    code="from pathlib import Path;from photoprep import diagnostics;import sys;diagnostics._path=Path(sys.argv[1]);[(diagnostics.event('child',index=i)) for i in range(10)]"
    processes=[subprocess.Popen([sys.executable,'-c',code,str(path)]) for _ in range(4)]
    assert all(p.wait(timeout=15)==0 for p in processes)
    assert len([json.loads(line) for line in path.read_text().splitlines()])==40


def test_logging_failure_does_not_break_application(tmp_path,monkeypatch):
    parent=tmp_path/'not-a-directory';parent.write_text('keep')
    monkeypatch.setattr(diagnostics,'_path',parent/'photoprep.log')
    diagnostics.error('failure',ValueError('expected test failure'))
    assert parent.read_text()=='keep'
