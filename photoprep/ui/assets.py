"""Resource lookup from checkout and editable installation."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def icon_path(name: str) -> str:
    return str(ROOT / "assets" / "icons" / (name + ".png"))


def app_icon_path() -> str:
    return str(ROOT / "assets" / "app-icon.png")
