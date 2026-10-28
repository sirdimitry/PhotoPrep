"""Shared, output-relative logo geometry for the canvas and export compositor."""
from dataclasses import dataclass,replace
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImageReader,QColorSpace


@dataclass(frozen=True)
class LogoPlacement:
    path: str
    width: float = .15
    opacity: float = 1.
    x: float = 1.
    y: float = 1.
    enabled: bool = True


def read_logo(path):
    file=Path(path)
    if not file.is_file() or file.stat().st_size>16*1024*1024:
        raise ValueError('logo_invalid')
    reader=QImageReader(str(file));reader.setAutoTransform(True)
    size=reader.size()
    if bytes(reader.format()).lower()!=b'png' or not size.isValid() or size.width()*size.height()>4_000_000:
        raise ValueError('logo_invalid')
    image=reader.read()
    if image.isNull():raise ValueError('logo_invalid')
    if image.colorSpace().isValid():
        image=image.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return image


def logo_area(bounds):
    return bounds.adjusted(bounds.width()*.03,bounds.height()*.03,-bounds.width()*.03,-bounds.height()*.03)


def logo_rect(bounds,placement,image):
    area=logo_area(bounds)
    aspect=image.height()/max(1,image.width())
    width=min(bounds.width()*placement.width,area.width(),area.height()/aspect)
    height=width*aspect
    return QRectF(area.left()+(area.width()-width)*placement.x,
                  area.top()+(area.height()-height)*placement.y,width,height)


def moved_logo(bounds,placement,image,delta):
    area=logo_area(bounds);rect=logo_rect(bounds,placement,image)
    dx,dy=area.width()-rect.width(),area.height()-rect.height()
    return replace(placement,x=min(1,max(0,placement.x+delta.x()/dx)) if dx>1e-9 else placement.x,
                   y=min(1,max(0,placement.y+delta.y()/dy)) if dy>1e-9 else placement.y)
