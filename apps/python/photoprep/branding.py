"""Shared, output-relative logo geometry for the canvas and export compositor."""
from dataclasses import dataclass,replace
from pathlib import Path

from PySide6.QtCore import QRectF,QRect
from PySide6.QtGui import QImageReader,QColorSpace


@dataclass(frozen=True)
class LogoPlacement:
    path: str
    width: float = .15
    opacity: float = 1.
    x: float = 1.
    y: float = 1.
    enabled: bool = True
    mode: str = "logo"


MAX_LOGO_PIXELS=32_000_000


def _read_png(path):
    file=Path(path)
    if not file.is_file() or file.stat().st_size>32*1024*1024:
        raise ValueError('logo_invalid')
    reader=QImageReader(str(file));reader.setAutoTransform(True)
    size=reader.size()
    if bytes(reader.format()).lower()!=b'png' or not size.isValid() or size.width()*size.height()>MAX_LOGO_PIXELS:
        raise ValueError('logo_invalid')
    image=reader.read()
    if image.isNull():raise ValueError('logo_invalid')
    if image.colorSpace().isValid():
        image=image.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    return image


def alpha_bounds(image):
    from PIL import Image
    from PySide6.QtGui import QImage
    rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels=Image.frombuffer('RGBA',(rgba.width(),rgba.height()),rgba.constBits(),'raw','RGBA',rgba.bytesPerLine(),1)
    box=pixels.getchannel('A').getbbox()
    if box is None:raise ValueError('logo_invalid')
    return QRect(box[0],box[1],box[2]-box[0],box[3]-box[1])


def read_logo(path,mode='logo'):
    image=_read_png(path)
    if mode=='template':image=image.copy(alpha_bounds(image))
    return image


def placement_from_path(path,mode=None):
    image=_read_png(path);box=alpha_bounds(image)
    if mode is None:
        mode='template' if box.width()*box.height()<image.width()*image.height()*.5 else 'logo'
    if mode not in ('template','logo'):raise ValueError('logo_invalid')
    if mode=='logo':return LogoPlacement(str(Path(path).resolve()),x=0,y=0)
    # Keep visible pixels, not the large transparent canvas. Record relative
    # size and edge offsets so any later output dimensions preserve the mark.
    width=box.width()/image.width()
    x=box.left()/max(1,image.width()-box.width())
    y=box.top()/max(1,image.height()-box.height())
    return LogoPlacement(str(Path(path).resolve()),width=max(.01,min(.94,width)),x=x,y=y,mode='template')


def template_catalog(folder):
    """Read local PNG headers only; never copy or package the user's assets."""
    root=Path(folder)
    entries=[]
    if not root.is_dir():return entries
    for path in root.rglob('*'):
        relative=path.relative_to(root)
        if len(relative.parts)>3 or any(part.startswith('.') for part in relative.parts) or path.is_symlink() or path.suffix.lower()!='.png':continue
        reader=QImageReader(str(path));size=reader.size()
        if not size.isValid() or size.width()*size.height()>MAX_LOGO_PIXELS:continue
        if bytes(reader.format()).lower()!=b'png' or path.stat().st_size>32*1024*1024:continue
        text=str(relative).casefold()
        landscape=size.width()>size.height()
        wide=abs(size.width()/size.height()-16/9)<.02
        left=any(word in text for word in ('слева','left','приоритет','priority'))
        group=0 if landscape and wide and left else 1 if landscape and wide else 2
        entries.append((group,str(relative),path.resolve()))
        if len(entries)>=256:break
    return sorted(entries,key=lambda item:(item[0],item[1].casefold()))


def logo_area(bounds,placement=None):
    if placement and placement.mode=='template':return QRectF(bounds)
    return bounds.adjusted(bounds.width()*.03,bounds.height()*.03,-bounds.width()*.03,-bounds.height()*.03)


def logo_rect(bounds,placement,image):
    area=logo_area(bounds,placement)
    aspect=image.height()/max(1,image.width())
    width=min(bounds.width()*placement.width,area.width(),area.height()/aspect)
    height=width*aspect
    return QRectF(area.left()+(area.width()-width)*placement.x,
                  area.top()+(area.height()-height)*placement.y,width,height)


def moved_logo(bounds,placement,image,delta):
    area=logo_area(bounds,placement);rect=logo_rect(bounds,placement,image)
    dx,dy=area.width()-rect.width(),area.height()-rect.height()
    return replace(placement,x=min(1,max(0,placement.x+delta.x()/dx)) if dx>1e-9 else placement.x,
                   y=min(1,max(0,placement.y+delta.y()/dy)) if dy>1e-9 else placement.y)
