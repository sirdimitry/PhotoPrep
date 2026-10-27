import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QImage
from photoprep.models import Photo, list_folder_images


def test_supported_image_and_folder(tmp_path):
    source = tmp_path / "a.png"
    assert QImage(23, 17, QImage.Format.Format_RGB32).save(str(source))
    (tmp_path / "ignore.txt").write_text("not a photo")
    assert list_folder_images(tmp_path) == [source]
    photo = Photo.from_path(source)
    assert photo is not None
    assert photo.width == 23
    assert photo.height == 17


def test_non_image_is_rejected(tmp_path):
    assert Photo.from_path(tmp_path / "missing.png") is None
