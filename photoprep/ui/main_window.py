"""Stage 1 PhotoPrep main window: workspace, navigation, import, settings.

No image processing or export occurs in this stage. All input image files are read-only.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImageReader, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import __version__
from ..i18n import tr
from ..models import Photo, list_folder_images
from ..settings import Preferences
from .assets import app_icon_path, icon_path
from .canvas import PhotoCanvas
from .preferences_dialog import PreferencesDialog
from .theme import STYLESHEET


class DropSurface(QFrame):
    """A friendly empty-state surface that forwards drop events to MainWindow."""

    def __init__(self, open_callback, drop_callback, t, parent=None):
        super().__init__(parent)
        self.drop_callback = drop_callback
        self.setAcceptDrops(True)
        self.setObjectName("Workspace")
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(35, 30, 35, 30)
        self.layout_.addStretch(1)
        self.panel = QFrame()
        self.panel.setObjectName("InfoCard")
        self.panel.setMaximumWidth(470)
        inner = QVBoxLayout(self.panel)
        inner.setSpacing(12)
        inner.setContentsMargins(38, 34, 38, 34)
        graphic = QLabel("▧")
        graphic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        graphic.setStyleSheet("font-size: 45px; color: #FACC15; border:0; background:transparent")
        inner.addWidget(graphic)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-size:22px;font-weight:750;color:#F7F7F8;background:transparent;border:0")
        inner.addWidget(self.title)
        self.hint = QLabel()
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Muted")
        self.hint.setStyleSheet("background:transparent; border:0; color:#A7ABB3")
        inner.addWidget(self.hint)
        self.open_button = QPushButton()
        self.open_button.setObjectName("Primary")
        self.open_button.setMinimumHeight(40)
        self.open_button.clicked.connect(open_callback)
        inner.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.formats = QLabel()
        self.formats.setObjectName("SmallHint")
        self.formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formats.setStyleSheet("background:transparent; border:0; color:#7D848D")
        inner.addWidget(self.formats)
        self.layout_.addWidget(self.panel, alignment=Qt.AlignmentFlag.AlignCenter)
        self.layout_.addStretch(1)
        self.retranslate(t)

    def retranslate(self, t):
        self.title.setText(t("drop_title"))
        self.hint.setText(t("drop_hint"))
        self.open_button.setText(t("open_photos"))
        self.formats.setText(t("drop_formats"))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        self.drop_callback([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Preferences()
        self.photos: list[Photo] = []
        self._indices: dict[Path, int] = {}
        self.setWindowTitle("PhotoPrep")
        self.setWindowIcon(QIcon(app_icon_path()))
        self.setStyleSheet(STYLESHEET)
        self.resize(1440, 900)
        self.setMinimumSize(940, 620)

        root = QWidget()
        self.setCentralWidget(root)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_header())
        shell.addWidget(self._build_body(), stretch=1)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(self.t("status_empty"))
        self._setup_shortcuts()
        self.retranslate()

    def t(self, key: str, **data) -> str:
        return tr(self.settings.language, key, **data)

    def _tool_button(self, icon: str, label: str = "", *, rail: bool = False) -> QToolButton:
        button = QToolButton()
        button.setIcon(QIcon(icon_path(icon)))
        button.setIconSize(QSize(21, 21))
        button.setText(label)
        if rail:
            button.setObjectName("RailButton")
        else:
            button.setObjectName("HeaderButton")
        return button

    def _build_header(self):
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(67)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)
        emblem = QLabel()
        emblem.setPixmap(QPixmap(app_icon_path()).scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(emblem)
        wordmark = QLabel('Photo<span style="color:#FACC15">Prep</span>')
        wordmark.setObjectName("BrandName")
        wordmark.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(wordmark)
        badge = QLabel("ALPHA 0.1")
        badge.setObjectName("Badge")
        layout.addSpacing(2)
        layout.addWidget(badge)
        layout.addSpacing(15)
        header_separator = QFrame()
        header_separator.setFixedSize(1, 26)
        header_separator.setStyleSheet("background:#3A3D43")
        layout.addWidget(header_separator)
        layout.addSpacing(8)
        self.open_files_button = QPushButton()
        self.open_files_button.setIcon(QIcon(icon_path("files")))
        self.open_files_button.setIconSize(QSize(18,18))
        self.open_files_button.setObjectName("Primary")
        self.open_files_button.clicked.connect(self.open_photos)
        layout.addWidget(self.open_files_button)
        self.open_folder_button = QPushButton()
        self.open_folder_button.setIcon(QIcon(icon_path("folder")))
        self.open_folder_button.setIconSize(QSize(18, 18))
        self.open_folder_button.clicked.connect(self.open_folder)
        layout.addWidget(self.open_folder_button)
        layout.addStretch(1)
        self.export_button = QPushButton()
        self.export_button.setObjectName("Primary")
        self.export_button.setIcon(QIcon(icon_path("export")))
        self.export_button.setEnabled(False)
        layout.addWidget(self.export_button)
        self.settings_button = self._tool_button("settings")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)
        return header

    def _build_body(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_rail())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_inspector())
        splitter.setSizes([60, 1080, 278])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.handle(1).setEnabled(False)
        splitter.handle(2).setEnabled(False)
        return splitter

    def _build_rail(self):
        rail = QWidget()
        rail.setObjectName("ToolRail")
        rail.setFixedWidth(60)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(10, 16, 10, 12)
        layout.setSpacing(7)
        self.tools = {}
        for key, icon in [("select", "move"), ("mask", "brush"), ("erase", "eraser"),
                          ("crop", "crop"), ("logo", "logo"), ("compare", "compare")]:
            button = self._tool_button(icon, rail=True)
            button.setToolTip(key)
            if key == "select":
                button.setCheckable(True)
                button.setChecked(True)
            else:
                button.setEnabled(False)
            self.tools[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.rail_info = self._tool_button("info", rail=True)
        self.rail_info.setEnabled(False)
        layout.addWidget(self.rail_info)
        return rail

    def _build_center(self):
        center = QWidget()
        center.setObjectName("Workspace")
        container = QVBoxLayout(center)
        container.setContentsMargins(0, 0, 0, 0)
        container.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("ImageBar")
        bar.setFixedHeight(51)
        horizontal = QHBoxLayout(bar)
        horizontal.setContentsMargins(18, 0, 18, 0)
        horizontal.setSpacing(9)
        self.photo_label = QLabel()
        self.photo_label.setStyleSheet("font-weight:600;background:transparent;")
        self.photo_label.setMinimumWidth(180)
        self.photo_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        horizontal.addWidget(self.photo_label, stretch=1)
        self.zoom_out_button = self._tool_button("zoom-out")
        self.zoom_out_button.clicked.connect(lambda: self.canvas.zoom(1 / 1.15))
        horizontal.addWidget(self.zoom_out_button)
        self.zoom_value = QLabel("100%")
        self.zoom_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_value.setFixedWidth(48)
        horizontal.addWidget(self.zoom_value)
        self.zoom_in_button = self._tool_button("zoom-in")
        self.zoom_in_button.clicked.connect(lambda: self.canvas.zoom(1.15))
        horizontal.addWidget(self.zoom_in_button)
        self.actual_button = QPushButton()
        self.actual_button.clicked.connect(self._actual)
        horizontal.addWidget(self.actual_button)
        self.fit_button = QPushButton()
        self.fit_button.clicked.connect(self._fit)
        horizontal.addWidget(self.fit_button)
        container.addWidget(bar)

        self.stack = QStackedWidget()
        self.empty = DropSurface(self.open_photos, self.import_paths, self.t)
        self.canvas = PhotoCanvas()
        self.canvas.zoom_changed.connect(lambda value: self.zoom_value.setText(f"{value}%"))
        self.canvas.files_dropped.connect(self.import_paths)
        self.canvas.setAcceptDrops(True)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas)
        container.addWidget(self.stack, stretch=1)

        strip = QWidget()
        strip.setObjectName("FilmstripPanel")
        strip.setFixedHeight(146)
        vertical = QVBoxLayout(strip)
        vertical.setContentsMargins(13, 9, 13, 8)
        vertical.setSpacing(5)
        self.strip_title = QLabel()
        self.strip_title.setObjectName("SectionTitle")
        vertical.addWidget(self.strip_title)
        self.thumbnails = QListWidget()
        self.thumbnails.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnails.setMovement(QListView.Movement.Static)
        self.thumbnails.setFlow(QListView.Flow.LeftToRight)
        self.thumbnails.setWrapping(False)
        self.thumbnails.setIconSize(QSize(126, 71))
        self.thumbnails.setGridSize(QSize(150, 104))
        self.thumbnails.setSpacing(1)
        self.thumbnails.setUniformItemSizes(True)
        self.thumbnails.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.thumbnails.currentRowChanged.connect(self.select_photo)
        vertical.addWidget(self.thumbnails, stretch=1)
        container.addWidget(strip)
        return center

    def _info_row(self, parent, title: str = "", value: str = ""):
        group = QVBoxLayout()
        group.setSpacing(3)
        top = QLabel(title)
        top.setObjectName("SmallHint")
        bottom = QLabel(value)
        bottom.setObjectName("Value")
        bottom.setWordWrap(True)
        group.addWidget(top)
        group.addWidget(bottom)
        parent.addLayout(group)
        return top, bottom

    def _build_inspector(self):
        panel = QWidget()
        panel.setObjectName("Inspector")
        panel.setMinimumWidth(242)
        panel.setMaximumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 22, 19, 17)
        layout.setSpacing(18)
        self.inspector_label = QLabel()
        self.inspector_label.setObjectName("SectionTitle")
        layout.addWidget(self.inspector_label)
        sep = QFrame()
        sep.setObjectName("Divider")
        layout.addWidget(sep)
        self.image_heading = QLabel()
        self.image_heading.setObjectName("SectionTitle")
        layout.addWidget(self.image_heading)
        self.filename_title, self.filename_value = self._info_row(layout)
        self.source_title, self.source_value = self._info_row(layout)
        self.export_title, self.export_value = self._info_row(layout)
        sep2 = QFrame()
        sep2.setObjectName("Divider")
        layout.addWidget(sep2)
        self.workflow_heading = QLabel()
        self.workflow_heading.setObjectName("SectionTitle")
        layout.addWidget(self.workflow_heading)
        self.steps = []
        for i in range(5):
            row = QHBoxLayout()
            bullet = QLabel("●" if i == 0 else "○")
            bullet.setStyleSheet("color:#FACC15" if i == 0 else "color:#696E77")
            row.addWidget(bullet)
            label = QLabel()
            label.setObjectName("Muted")
            row.addWidget(label, stretch=1)
            self.steps.append(label)
            layout.addLayout(row)
        layout.addStretch(1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("SmallHint")
        layout.addWidget(self.note)
        return panel

    def _setup_shortcuts(self):
        for seq, target in [
            (QKeySequence.StandardKey.Open, self.open_photos),
            ("Ctrl+Shift+O", self.open_folder),
            ("Ctrl+0", self._fit),
            ("Ctrl+1", self._actual),
            ("Ctrl++", lambda: self.canvas.zoom(1.15)),
            ("Ctrl+-", lambda: self.canvas.zoom(1 / 1.15)),
        ]:
            shortcut = QShortcut(seq if isinstance(seq, QKeySequence) else QKeySequence(seq), self)
            shortcut.activated.connect(target)

    def _fit(self):
        self.canvas.fit_photo()

    def _actual(self):
        self.canvas.actual_size()

    def open_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.t("dialog_open"), str(Path.home()), self.t("dialog_filter"))
        if paths:
            self.import_paths(paths)

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("dialog_folder"), str(Path.home()))
        if folder:
            self.import_paths([folder])

    def import_paths(self, paths: list[str]):
        image_paths = []
        for path in paths:
            file = Path(path)
            if file.is_dir():
                image_paths.extend(list_folder_images(file))
            else:
                image_paths.append(file)
        added = 0
        for path in image_paths:
            file = Path(path).expanduser().resolve()
            if file in self._indices:
                continue
            photo = Photo.from_path(file)
            if photo is None:
                continue
            reader = QImageReader(str(file))
            reader.setAutoTransform(True)
            natural_size = reader.size()
            if natural_size.isValid():
                reader.setScaledSize(natural_size.scaled(QSize(126, 80), Qt.AspectRatioMode.KeepAspectRatio))
            thumbnail = reader.read()
            if thumbnail.isNull():
                continue
            self._indices[file] = len(self.photos)
            self.photos.append(photo)
            item = QListWidgetItem(QIcon(QPixmap.fromImage(thumbnail)), file.name)
            item.setToolTip(str(file))
            item.setSizeHint(QSize(150, 104))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumbnails.addItem(item)
            added += 1
        if added:
            self.stack.setCurrentWidget(self.canvas)
            if self.thumbnails.currentRow() < 0:
                self.thumbnails.setCurrentRow(0)
            else:
                # Keep selection, but update photo count.
                self._update_info(self.photos[self.thumbnails.currentRow()])
            self.statusBar().showMessage(self.t("status_loaded", count=len(self.photos)), 6000)
        elif not self.photos:
            QMessageBox.information(self, "PhotoPrep", self.t("no_images"))
        self._refresh_controls()
        self.strip_title.setText(f'{self.t("photos")}  ·  {len(self.photos)}')

    def select_photo(self, index: int):
        if not 0 <= index < len(self.photos):
            return
        photo = self.photos[index]
        if not self.canvas.load_photo(str(photo.path)):
            QMessageBox.warning(self, "PhotoPrep", self.t("invalid_image", path=photo.path.name))
            return
        self._update_info(photo)
        self._refresh_controls()

    def _update_info(self, photo: Photo):
        self.photo_label.setText(photo.path.name)
        self.filename_value.setText(photo.path.name)
        self.source_value.setText(f"{photo.width} × {photo.height} px")
        self.export_value.setText(f"{self.settings.output_width} × {self.settings.output_height} px")

    def _refresh_controls(self):
        enabled = self.canvas.has_photo
        for button in (self.fit_button, self.actual_button, self.zoom_in_button, self.zoom_out_button):
            button.setEnabled(enabled)

    def open_settings(self):
        dialog = PreferencesDialog(self.settings, self)
        dialog.applied.connect(self.retranslate)
        dialog.exec()

    def retranslate(self):
        t = self.t
        self.open_files_button.setText(t("open_photos"))
        self.open_folder_button.setText(t("open_folder"))
        self.export_button.setText(t("export"))
        self.export_button.setToolTip(t("coming_soon"))
        self.settings_button.setToolTip(t("settings"))
        self.photo_label.setText(self.photos[self.thumbnails.currentRow()].path.name if self.photos and self.thumbnails.currentRow() >= 0 else t("no_photo"))
        self.fit_button.setText(t("fit"))
        self.actual_button.setText(t("actual"))
        self.zoom_in_button.setToolTip(t("zoom_in"))
        self.zoom_out_button.setToolTip(t("zoom_out"))
        for key, button in self.tools.items():
            button.setToolTip(t(key) + (" · " + t("coming_soon") if key != "select" else ""))
        self.empty.retranslate(t)
        self.strip_title.setText(f'{t("photos")}  ·  {len(self.photos)}')
        self.inspector_label.setText(t("inspect"))
        self.image_heading.setText(t("image"))
        self.filename_title.setText(t("filename"))
        self.source_title.setText(t("source_size"))
        self.export_title.setText(t("export_preset"))
        self.workflow_heading.setText(t("workflow"))
        for label, key in zip(self.steps, ("step_import", "step_restore", "step_crop", "step_brand", "step_export")):
            label.setText(t(key))
        self.note.setText(t("stage_ready"))
        self.filename_value.setText(self.photos[self.thumbnails.currentRow()].path.name if self.photos and self.thumbnails.currentRow() >= 0 else "—")
        self.source_value.setText("—" if not self.photos or self.thumbnails.currentRow() < 0 else f"{self.photos[self.thumbnails.currentRow()].width} × {self.photos[self.thumbnails.currentRow()].height} px")
        self.export_value.setText(f"{self.settings.output_width} × {self.settings.output_height} px")
        self._refresh_controls()
