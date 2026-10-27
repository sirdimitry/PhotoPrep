from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_brand_assets():
    assert (ROOT / "assets" / "app-icon.svg").is_file()
    with Image.open(ROOT / "assets" / "app-icon.png") as img:
        assert img.size == (1024, 1024)
    with Image.open(ROOT / "assets" / "github-banner.png") as img:
        assert img.width > 2 * img.height
