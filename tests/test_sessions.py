"""Workspaces remain reversible and portable without copying source pixels."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from photoprep.models import Photo
from photoprep.session import SessionError, load_session, save_session
from photoprep.workspace import ViewState, Workspace


@pytest.fixture
def photos(tmp_path):
    result = []
    for name in ('первое.png', 'second.png', 'third.png'):
        path = tmp_path / name
        Image.new('RGB', (120, 80), 'yellow').save(path)
        result.append(Photo.from_path(path))
    return result


def test_history_deduplication_and_removed_view(photos):
    workspace = Workspace()
    assert not workspace.dirty
    assert workspace.add([photos[0], photos[0], photos[1]]) == 2
    workspace.selected = photos[1].path
    workspace.views[photos[1].path] = ViewState(False, 2, .7, .6)
    workspace.mark_saved()
    assert workspace.remove_selected()
    assert workspace.selected == photos[0].path
    assert workspace.dirty
    assert workspace.undo()
    assert not workspace.dirty
    assert workspace.selected == photos[1].path
    assert workspace.views[photos[1].path].zoom == 2
    assert workspace.redo()
    assert workspace.add([photos[2]]) == 1
    assert not workspace.can_redo
    assert all(p.path.exists() for p in photos)


def test_session_roundtrip_relative_paths_and_source_integrity(photos, tmp_path):
    workspace = Workspace()
    workspace.add(photos)
    workspace.selected = photos[1].path
    workspace.views[photos[0].path] = ViewState(False, 3, .7, .6)
    hashes = {p.path: hashlib.sha256(p.path.read_bytes()).hexdigest() for p in photos}
    path = tmp_path / 'съёмка.photoprep.json'
    save_session(path, workspace)
    payload = json.loads(path.read_text())
    assert not Path(payload['photos'][0]['path']).is_absolute()
    assert 'pixels' not in payload
    restored, skipped = load_session(path)
    assert skipped == 0
    assert restored.snapshot() == workspace.snapshot()
    assert not restored.dirty
    assert not restored.can_undo
    assert hashes == {p.path: hashlib.sha256(p.path.read_bytes()).hexdigest() for p in photos}


def test_missing_photo_falls_back_without_deleting_other_files(photos, tmp_path):
    workspace = Workspace()
    workspace.add(photos)
    workspace.selected = photos[1].path
    path = tmp_path / 'set.photoprep.json'
    save_session(path, workspace)
    photos[1].path.unlink()  # Simulates a source moved outside PhotoPrep.
    restored, skipped = load_session(path)
    assert skipped == 1
    assert restored.photos == [photos[0], photos[2]]
    assert restored.selected == photos[0].path
    assert photos[0].path.exists() and photos[2].path.exists()


@pytest.mark.parametrize('payload', ['not json', '[]', '{"format":"PhotoPrep","version":9,"photos":[]}',
                                    '{"format":"PhotoPrep","version":1,"photos":[{"path":2}]}'])
def test_invalid_session_is_rejected(tmp_path, payload):
    path = tmp_path / 'bad.photoprep.json'
    path.write_text(payload)
    with pytest.raises(SessionError):
        load_session(path)


def test_large_session_is_rejected_before_parsing(tmp_path, monkeypatch):
    import photoprep.session as session
    monkeypatch.setattr(session, 'MAX_SESSION_BYTES', 100)
    path = tmp_path / 'large.photoprep.json'
    path.write_bytes(b' ' * 101)
    with pytest.raises(SessionError, match='session_too_large'):
        load_session(path)


def test_invalid_view_numbers_are_safe(photos, tmp_path):
    path = tmp_path / 'view.photoprep.json'
    path.write_text(json.dumps({'format':'PhotoPrep', 'version':1, 'photos':[
        {'path':photos[0].path.name, 'view':{'fit':False, 'zoom':float('nan')}}]}))
    restored, _ = load_session(path)
    assert restored.views[photos[0].path] == ViewState()


def test_session_is_private_to_its_owner(photos, tmp_path):
    workspace = Workspace()
    workspace.add(photos)
    path = tmp_path/'private.photoprep.json'
    save_session(path, workspace)
    assert path.stat().st_mode & 0o777 == 0o600
