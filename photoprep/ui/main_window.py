"""PhotoPrep workspace: read-only photos, sessions, navigation and history.

No image processing or export occurs in this stage. All input image files are read-only.
"""
from __future__ import annotations

from pathlib import Path
from collections import OrderedDict

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImageReader, QPixmap, QKeySequence, QAction
from PySide6.QtWidgets import (
    QFrame, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget, QButtonGroup, QSlider, QCheckBox,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import __version__
from ..i18n import tr
from ..models import Photo, list_folder_images
from ..settings import Preferences
from ..workspace import Workspace, ViewState
from ..editing import PhotoEdits
from ..session import load_session, save_session, SessionError
from .assets import app_icon_path, icon_path
from .editor import EditorCanvas as PhotoCanvas
from .preferences_dialog import PreferencesDialog
from .theme import STYLESHEET
from .widgets import PhotoNameLabel


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
        self.workspace = Workspace(output_width=self.settings.output_width, output_height=self.settings.output_height)
        self.session_path: Path | None = None
        self._thumbnail_icons = OrderedDict()
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
        self._setup_actions()
        self.retranslate()

    @property
    def photos(self):
        return self.workspace.photos

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
        header.setFixedHeight(50)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)
        emblem = QLabel()
        emblem.setPixmap(QPixmap(app_icon_path()).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(emblem)
        wordmark = QLabel('Photo<span style="color:#FACC15">Prep</span>')
        wordmark.setObjectName("BrandName")
        wordmark.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(wordmark)
        badge = QLabel("ALPHA 0.1")
        badge.setObjectName("Badge")
        badge.setToolTip(__version__)
        layout.addSpacing(2)
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.photo_label = PhotoNameLabel()
        layout.addWidget(self.photo_label,stretch=1)
        layout.addSpacing(8)
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
        self.export_button = QPushButton()
        self.export_button.setObjectName("Primary")
        self.export_button.setIcon(QIcon(icon_path("export")))
        self.export_button.setEnabled(False)
        layout.addWidget(self.export_button)
        self.settings_button = self._tool_button("settings")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)
        for button in (self.open_files_button,self.open_folder_button,self.export_button):
            button.setProperty("compact",True)
            button.setFixedHeight(30)
        return header

    def _build_body(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_rail())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_inspector())
        splitter.setSizes([48, 1080, 278])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.handle(1).setEnabled(False)
        splitter.handle(2).setEnabled(False)
        return splitter

    def _build_rail(self):
        rail = QWidget()
        rail.setObjectName("ToolRail")
        rail.setFixedWidth(48)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(6, 12, 6, 10)
        layout.setSpacing(7)
        self.tools = {}
        self.tool_group = QButtonGroup(self)
        for key, icon in [("select", "move"), ("mask", "brush"), ("erase", "eraser"),
                          ("crop", "crop"), ("logo", "logo"), ("compare", "compare")]:
            button = self._tool_button(icon, rail=True)
            button.setToolTip(key)
            if key in ("select", "mask", "erase", "crop"):
                button.setCheckable(True)
                self.tool_group.addButton(button)
                button.setChecked(key == "select")
                button.toggled.connect(lambda checked, tool=key: self._select_tool(tool) if checked else None)
            button.setEnabled(key == "select")
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

        self.stack = QStackedWidget()
        self.empty = DropSurface(self.open_photos, self.import_paths, self.t)
        self.canvas = PhotoCanvas()
        self.canvas.zoom_changed.connect(lambda value: self.zoom_value.setText(f"{value}%"))
        self.canvas.files_dropped.connect(self.import_paths)
        self.canvas.photo_loaded.connect(self._photo_loaded)
        self.canvas.loading_changed.connect(self._loading_changed)
        self.canvas.view_changed.connect(self._view_changed)
        self.canvas.edits_committed.connect(self._edits_committed)
        self.canvas.crop_changed.connect(self._crop_info_changed)
        self.canvas.setAcceptDrops(True)
        self.tool_options = self._build_tool_options()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.canvas)
        container.addWidget(self.stack, stretch=1)

        strip = QWidget()
        strip.setObjectName("FilmstripPanel")
        strip.setFixedHeight(146)
        vertical = QVBoxLayout(strip)
        vertical.setContentsMargins(10, 5, 10, 5)
        vertical.setSpacing(4)
        self.strip_title = QLabel()
        self.strip_title.setObjectName("SectionTitle")
        strip_bar = QHBoxLayout()
        strip_bar.addWidget(self.strip_title)
        strip_bar.addStretch(1)
        self.zoom_out_button = self._tool_button("zoom-out")
        self.zoom_out_button.clicked.connect(lambda:self.canvas.zoom(1/1.15))
        self.zoom_value = QLabel("100%")
        self.zoom_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_value.setFixedWidth(44)
        self.zoom_in_button = self._tool_button("zoom-in")
        self.zoom_in_button.clicked.connect(lambda:self.canvas.zoom(1.15))
        self.actual_button, self.fit_button = QPushButton("100%"), QPushButton()
        self.actual_button.clicked.connect(self._actual)
        self.fit_button.clicked.connect(self._fit)
        for widget in (self.zoom_out_button,self.zoom_value,self.zoom_in_button,self.actual_button,self.fit_button):
            strip_bar.addWidget(widget)
        for button in (self.actual_button,self.fit_button):
            button.setProperty("compact",True)
            button.setFixedHeight(26)
        strip_bar.addSpacing(12)
        self.photo_position = QLabel()
        self.photo_position.setObjectName("SmallHint")
        strip_bar.addWidget(self.photo_position)
        self.previous_button = self._tool_button("chevron")
        self.previous_button.setIcon(QIcon())
        self.previous_button.setText("‹")
        self.previous_button.clicked.connect(lambda: self.navigate(-1))
        strip_bar.addWidget(self.previous_button)
        self.next_button = self._tool_button("chevron")
        self.next_button.setIcon(QIcon())
        self.next_button.setText("›")
        self.next_button.clicked.connect(lambda: self.navigate(1))
        strip_bar.addWidget(self.next_button)
        self.remove_button = self._tool_button("close")
        self.remove_button.clicked.connect(self.remove_photo)
        strip_bar.addWidget(self.remove_button)
        vertical.addLayout(strip_bar)
        self.thumbnails = QListWidget()
        self.thumbnails.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnails.setMovement(QListView.Movement.Static)
        self.thumbnails.setFlow(QListView.Flow.LeftToRight)
        self.thumbnails.setWrapping(False)
        self.thumbnails.setIconSize(QSize(116, 65))
        self.thumbnails.setGridSize(QSize(140, 94))
        self.thumbnails.setSpacing(1)
        self.thumbnails.setUniformItemSizes(True)
        self.thumbnails.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.thumbnails.currentRowChanged.connect(self.select_photo)
        vertical.addWidget(self.thumbnails, stretch=1)
        container.addWidget(strip)
        return center

    def _compact_tool_button(self, icon, callback):
        button=QToolButton()
        button.setObjectName("CompactAction")
        button.setIcon(QIcon(icon_path(icon)))
        button.setIconSize(QSize(16,16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setFixedHeight(28)
        button.clicked.connect(callback)
        return button

    def _build_tool_options(self):
        options=QStackedWidget()
        options.setObjectName("ToolOptions")
        options.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        mask=QWidget()
        layout=QVBoxLayout(mask)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(10)
        row=QHBoxLayout()
        self.brush_label=QLabel()
        self.brush_value=QLabel()
        self.brush_value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.brush_label)
        row.addStretch(1)
        row.addWidget(self.brush_value)
        layout.addLayout(row)
        self.brush_slider=QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(2,512)
        self.brush_slider.setValue(self.canvas.brush_size)
        self.brush_slider.setMaximumWidth(210)
        self.brush_slider.valueChanged.connect(self._brush_changed)
        layout.addWidget(self.brush_slider)
        self.show_mask=QCheckBox()
        self.show_mask.setChecked(True)
        self.show_mask.toggled.connect(self.canvas.set_mask_visible)
        layout.addWidget(self.show_mask)
        self.clear_mask_button=self._compact_tool_button("close",self.canvas.clear_mask)
        layout.addWidget(self.clear_mask_button,alignment=Qt.AlignmentFlag.AlignLeft)
        self.mask_hint=QLabel()
        self.mask_hint.setObjectName("SmallHint")
        self.mask_hint.setWordWrap(True)
        layout.addWidget(self.mask_hint)
        options.addWidget(mask)
        crop=QWidget()
        layout=QVBoxLayout(crop)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(10)
        self.crop_info=QLabel()
        self.crop_info.setObjectName("Value")
        layout.addWidget(self.crop_info)
        self.crop_hint=QLabel()
        self.crop_hint.setWordWrap(True)
        self.crop_hint.setObjectName("SmallHint")
        layout.addWidget(self.crop_hint)
        row=QHBoxLayout()
        self.fit_crop_button=self._compact_tool_button("fit",self.canvas.fit_crop_view)
        self.reset_crop_button=self._compact_tool_button("move",self.canvas.reset_crop)
        row.addWidget(self.fit_crop_button)
        row.addWidget(self.reset_crop_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.clear_crop_button=QToolButton(crop)
        self.clear_crop_button.hide()
        options.addWidget(crop)
        options.setVisible(False)
        return options

    def _select_tool(self, tool):
        if not self.tools[tool].isChecked():
            self.tools[tool].setChecked(True)
            return
        self._capture_view()
        self.canvas.set_tool(tool)
        self.tool_options.setCurrentIndex(1 if tool=="crop" else 0)
        self.tool_options.setVisible(tool!="select")
        self.tool_heading.setText(self.t(tool))
        self._refresh_controls()
        self.canvas.setFocus()

    def _brush_changed(self, value):
        self.canvas.set_brush_size(value)
        self.brush_value.setText(self.t("brush_pixels", size=value))

    def _crop_info_changed(self):
        if not hasattr(self,"crop_info"):
            return
        self.crop_info.setText(self.t("fixed_crop_dimensions",width=self.workspace.output_width,height=self.workspace.output_height))

    def _edits_committed(self, path, edits):
        self._capture_view(finish_stroke=False)
        if self.workspace.set_edits(Path(path), edits):
            self._refresh_controls()
            self._update_title()

    def _info_row(self, parent, title: str = "", value: str = ""):
        group = QVBoxLayout()
        group.setSpacing(3)
        top = QLabel(title)
        top.setObjectName("SmallHint")
        bottom = QLabel(value)
        bottom.setTextFormat(Qt.TextFormat.PlainText)
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
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(14)
        self.inspector_label = QLabel()
        self.inspector_label.setObjectName("SectionTitle")
        layout.addWidget(self.inspector_label)
        sep = QFrame()
        sep.setObjectName("Divider")
        layout.addWidget(sep)
        self.image_heading = QLabel()
        self.image_heading.setObjectName("SectionTitle")
        layout.addWidget(self.image_heading)
        self.source_title, self.source_value = self._info_row(layout)
        self.export_title, self.export_value = self._info_row(layout)
        sep2 = QFrame()
        sep2.setObjectName("Divider")
        layout.addWidget(sep2)
        self.tool_heading=QLabel()
        self.tool_heading.setObjectName("SectionTitle")
        layout.addWidget(self.tool_heading)
        layout.addWidget(self.tool_options)
        layout.addStretch(1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("SmallHint")
        layout.addWidget(self.note)
        return panel

    def _setup_actions(self):
        self.file_menu = self.menuBar().addMenu("")
        self.edit_menu = self.menuBar().addMenu("")
        self.view_menu = self.menuBar().addMenu("")
        self.actions = {}
        def action(menu, key, callback, shortcut=None):
            item = QAction(self)
            item.triggered.connect(callback)
            if shortcut is not None:
                item.setShortcut(shortcut)
            menu.addAction(item)
            self.actions[key] = item
            return item
        action(self.file_menu, "open_photos", self.open_photos, QKeySequence.StandardKey.Open)
        action(self.file_menu, "open_folder", self.open_folder, "Ctrl+Shift+O")
        self.file_menu.addSeparator()
        action(self.file_menu, "new_workspace", self.new_workspace, QKeySequence.StandardKey.New)
        action(self.file_menu, "open_workspace", self.open_workspace, "Ctrl+Alt+O")
        action(self.file_menu, "save_workspace", self.save_workspace, QKeySequence.StandardKey.Save)
        action(self.file_menu, "save_workspace_as", lambda: self.save_workspace(save_as=True), "Ctrl+Shift+S")
        action(self.edit_menu, "undo", self.undo, QKeySequence.StandardKey.Undo)
        action(self.edit_menu, "redo", self.redo, QKeySequence.StandardKey.Redo)
        self.edit_menu.addSeparator()
        item = action(self.edit_menu, "remove_photo", self.remove_photo)
        item.setShortcuts([QKeySequence(Qt.Key.Key_Backspace), QKeySequence(Qt.Key.Key_Delete)])
        action(self.view_menu, "previous_photo", lambda: self.navigate(-1), "Left")
        action(self.view_menu, "next_photo", lambda: self.navigate(1), "Right")
        self.view_menu.addSeparator()
        action(self.view_menu, "fit", self._fit, "Ctrl+0")
        action(self.view_menu, "actual", self._actual, "Ctrl+1")
        action(self.view_menu, "zoom_in", lambda: self.canvas.zoom(1.15), "Ctrl++")
        action(self.view_menu, "zoom_out", lambda: self.canvas.zoom(1 / 1.15), "Ctrl+-")
        self.view_menu.addSeparator()
        for key, shortcut in (("select","V"),("mask","B"),("erase","E"),("crop","C")):
            action(self.view_menu,key,lambda checked=False, tool=key: self._select_tool(tool),shortcut)
        action(self.view_menu,"brush_smaller",lambda: self.brush_slider.setValue(self.brush_slider.value()-5),"[")
        action(self.view_menu,"brush_larger",lambda: self.brush_slider.setValue(self.brush_slider.value()+5),"]")

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

    def _thumbnail(self, photo):
        try:
            stat = photo.path.stat()
            key = (photo.path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None
        if key in self._thumbnail_icons:
            icon = self._thumbnail_icons.pop(key)
            self._thumbnail_icons[key] = icon
            return icon
        reader = QImageReader(str(photo.path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(QSize(126, 80), Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return None
        icon = QIcon(QPixmap.fromImage(image))
        self._thumbnail_icons[key] = icon
        while len(self._thumbnail_icons) > 256:
            self._thumbnail_icons.popitem(last=False)
        return icon

    def import_paths(self, paths: list[str]):
        self._capture_view()
        image_paths = []
        for path in paths:
            try:
                file = Path(path).expanduser()
                image_paths.extend(list_folder_images(file) if file.is_dir() else [file])
            except (OSError, ValueError):
                continue
        known = {p.path for p in self.photos}
        photos = []
        for path in image_paths:
            try:
                photo = Photo.from_path(path)
                if photo is not None and photo.path not in known and self._thumbnail(photo) is not None:
                    photos.append(photo)
                    known.add(photo.path)
            except (OSError, ValueError, RuntimeError):
                continue
        added = self.workspace.add(photos)
        if added:
            self._present_workspace()
        else:
            self.statusBar().showMessage(self.t("no_new_images"), 6000)
        return added

    def _capture_view(self, *, finish_stroke=True):
        if finish_stroke:
            self.canvas.finish_edit()
        if self.canvas.view_dirty and self.canvas.current_path and Path(self.canvas.current_path) == self.workspace.selected:
            self.workspace.views[self.workspace.selected] = self.canvas.view_state()
            self.canvas.view_dirty = False

    def _view_changed(self):
        self._capture_view()
        self._update_title()

    def _update_title(self):
        name = self.session_path.name if self.session_path else self.t("untitled_workspace")
        self.setWindowTitle(f"PhotoPrep — {name}[*]")
        self.setWindowModified(self.workspace.dirty)

    def _present_workspace(self):
        self.canvas.set_crop_ratio(self.workspace.output_width/self.workspace.output_height)
        self.thumbnails.blockSignals(True)
        try:
            self.thumbnails.clear()
            for photo in self.photos:
                item = QListWidgetItem(self._thumbnail(photo) or QIcon(), photo.path.name)
                item.setToolTip(str(photo.path))
                item.setSizeHint(QSize(140, 94))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.thumbnails.addItem(item)
            self.thumbnails.setCurrentRow(self.workspace.index)
        finally:
            self.thumbnails.blockSignals(False)
        if self.workspace.index >= 0:
            self.stack.setCurrentWidget(self.canvas)
            photo = self.photos[self.workspace.index]
            self._update_info(photo)
            self.canvas.load_photo(str(photo.path), self.workspace.views.get(photo.path, ViewState()))
        else:
            self.canvas.clear_photo()
            self.stack.setCurrentWidget(self.empty)
            self._select_tool("select")
        self.retranslate()

    def select_photo(self, index: int):
        if not 0 <= index < len(self.photos):
            return
        self._capture_view()
        photo = self.photos[index]
        self.workspace.selected = photo.path
        self._update_info(photo)
        self.canvas.load_photo(str(photo.path), self.workspace.views.get(photo.path, ViewState()))
        self._refresh_controls()
        self._update_title()

    def _loading_changed(self, loading):
        self._refresh_controls()
        if loading:
            self.statusBar().showMessage(self.t("loading_photo"))

    def _photo_loaded(self, path, success):
        if success:
            self.canvas.set_crop_ratio(self.workspace.output_width/self.workspace.output_height)
            self.canvas.set_edits(self.workspace.edits.get(Path(path), PhotoEdits()))
        self._refresh_controls()
        self.statusBar().showMessage(self.t("status_loaded", count=len(self.photos)) if success
                                     else self.t("invalid_image", path=Path(path).name))

    def navigate(self, delta):
        index = self.workspace.index + delta
        if 0 <= index < len(self.photos):
            self.thumbnails.setCurrentRow(index)

    def remove_photo(self):
        self._capture_view()
        if self.workspace.remove_selected():
            self._present_workspace()
            self.statusBar().showMessage(self.t("removed_from_workspace"), 6000)

    def undo(self):
        self._capture_view()
        if self.workspace.undo():
            self._present_workspace()

    def redo(self):
        self._capture_view()
        if self.workspace.redo():
            self._present_workspace()

    def new_workspace(self):
        if not self._confirm_discard():
            return
        self.workspace = Workspace(output_width=self.settings.output_width, output_height=self.settings.output_height)
        self.session_path = None
        self._present_workspace()

    def open_workspace(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("open_workspace"), str(Path.home()), self.t("workspace_filter"))
        if path:
            self.open_session_file(Path(path))

    def open_session_file(self, path: Path):
        try:
            workspace, skipped = load_session(path)
        except (OSError, SessionError) as exc:
            key = str(exc) if isinstance(exc, SessionError) else "session_open_error"
            QMessageBox.warning(self, "PhotoPrep", self.t(key))
            return False
        if not self._confirm_discard():
            return False
        self.workspace = workspace
        self.session_path = path.expanduser().resolve()
        self._present_workspace()
        if skipped:
            QMessageBox.information(self, "PhotoPrep", self.t("session_skipped", count=skipped))
        return True

    def save_workspace(self, checked=False, *, save_as=False):
        self._capture_view()
        path = self.session_path
        if path is None or save_as:
            path_text, _ = QFileDialog.getSaveFileName(
                self, self.t("save_workspace"), str(path or Path.home() / "Untitled.photoprep.json"), self.t("workspace_filter"))
            if not path_text:
                return False
            if not path_text.lower().endswith(".photoprep.json"):
                path_text += ".photoprep.json"
            path = Path(path_text)
        try:
            save_session(path, self.workspace)
        except (OSError, SessionError):
            QMessageBox.warning(self, "PhotoPrep", self.t("session_save_error"))
            return False
        self.session_path = path.resolve()
        self.workspace.mark_saved()
        self._update_title()
        self.statusBar().showMessage(self.t("session_saved"), 6000)
        return True

    def _confirm_discard(self):
        self._capture_view()
        if not self.workspace.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(self.t("unsaved_title"))
        box.setText(self.t("unsaved_message"))
        box.setIcon(QMessageBox.Icon.Question)
        save = box.addButton(self.t("save"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(self.t("discard"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.t("cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() == save:
            return self.save_workspace()
        return box.clickedButton() == discard

    def closeEvent(self, event):
        if self._confirm_discard():
            self.canvas.clear_photo()
            event.accept()
        else:
            event.ignore()

    def _update_info(self, photo: Photo):
        self.photo_label.set_filename(photo.path.name)
        self.source_value.setText(f"{photo.width} × {photo.height} px")
        self.export_value.setText(f"{self.workspace.output_width} × {self.workspace.output_height} px")

    def _refresh_controls(self):
        enabled = self.canvas.has_photo
        for button in (self.fit_button, self.actual_button, self.zoom_in_button, self.zoom_out_button):
            button.setEnabled(enabled)
        index = self.workspace.index
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(0 <= index < len(self.photos) - 1)
        self.remove_button.setEnabled(index >= 0)
        for tool in ("mask","erase","crop"):
            self.tools[tool].setEnabled(enabled)
        self.tool_options.setEnabled(enabled)
        edits = self.workspace.edits.get(self.workspace.selected,PhotoEdits())
        self.clear_mask_button.setEnabled(enabled and bool(edits.strokes))
        self.clear_crop_button.setEnabled(enabled and edits.crop is not None)
        self.reset_crop_button.setEnabled(enabled)
        self.fit_crop_button.setEnabled(enabled)
        self.photo_position.setText(self.t("images_loaded", index=index + 1, total=len(self.photos)) if self.photos else "")
        if hasattr(self, "actions"):
            self.actions["undo"].setEnabled(self.workspace.can_undo)
            self.actions["redo"].setEnabled(self.workspace.can_redo)
            self.actions["remove_photo"].setEnabled(index >= 0)
            self.actions["previous_photo"].setEnabled(index > 0)
            self.actions["next_photo"].setEnabled(0 <= index < len(self.photos) - 1)
            for key in ("fit", "actual", "zoom_in", "zoom_out", "mask", "erase", "crop", "brush_smaller", "brush_larger"):
                self.actions[key].setEnabled(enabled)

    def open_settings(self):
        dialog = PreferencesDialog(self.settings, self, dimensions=(self.workspace.output_width,self.workspace.output_height))
        dialog.applied.connect(self._preferences_applied)
        dialog.exec()

    def _preferences_applied(self):
        self._capture_view()
        self.workspace.set_output_size(self.settings.output_width,self.settings.output_height)
        self.canvas.set_crop_ratio(self.workspace.output_width/self.workspace.output_height)
        if self.workspace.selected:
            self.canvas.set_edits(self.workspace.edits.get(self.workspace.selected,PhotoEdits()))
        self.retranslate()

    def retranslate(self):
        t = self.t
        self.file_menu.setTitle(t("file_menu"))
        self.edit_menu.setTitle(t("edit_menu"))
        self.view_menu.setTitle(t("view_menu"))
        for key, action in self.actions.items():
            action.setText(t(key))
        self.brush_label.setText(t("brush_size"))
        self.brush_value.setText(t("brush_pixels",size=self.canvas.brush_size))
        self.brush_slider.setAccessibleName(t("brush_size"))
        self.show_mask.setText(t("show_mask"))
        self.clear_mask_button.setText(t("clear_mask"))
        self.mask_hint.setText(t("mask_controls_hint"))
        self.tool_heading.setText(t(self.canvas.tool))
        self.crop_hint.setText(t("crop_controls_hint"))
        self.reset_crop_button.setText(t("center_crop"))
        self.reset_crop_button.setToolTip(t("reset_crop"))
        self.fit_crop_button.setText(t("fill_crop_short"))
        self.fit_crop_button.setToolTip(t("fill_crop"))
        self.clear_crop_button.setText(t("clear_crop"))
        self._crop_info_changed()
        self.previous_button.setToolTip(t("previous_photo"))
        self.previous_button.setAccessibleName(t("previous_photo"))
        self.next_button.setToolTip(t("next_photo"))
        self.next_button.setAccessibleName(t("next_photo"))
        self.remove_button.setToolTip(t("remove_photo"))
        self.remove_button.setAccessibleName(t("remove_photo"))
        self._update_title()
        self.open_files_button.setText(t("open_photos"))
        self.open_folder_button.setText(t("open_folder"))
        self.export_button.setText(t("export"))
        self.export_button.setToolTip(t("coming_soon"))
        self.settings_button.setToolTip(t("settings"))
        self.photo_label.set_filename(self.photos[self.thumbnails.currentRow()].path.name if self.photos and self.thumbnails.currentRow() >= 0 else "")
        self.fit_button.setText(t("fit"))
        self.actual_button.setText(t("actual"))
        self.zoom_in_button.setToolTip(t("zoom_in"))
        self.zoom_out_button.setToolTip(t("zoom_out"))
        for key, button in self.tools.items():
            button.setToolTip(t(key) + (" · " + t("coming_soon") if key not in ("select","mask","erase","crop") else ""))
        self.empty.retranslate(t)
        self.strip_title.setText(f'{t("photos")}  ·  {len(self.photos)}')
        self.inspector_label.setText(t("inspect"))
        self.image_heading.setText(t("image"))
        self.source_title.setText(t("source_size"))
        self.export_title.setText(t("export_preset"))
        self.note.setText(t("stage_ready"))
        self.source_value.setText("—" if not self.photos or self.thumbnails.currentRow() < 0 else f"{self.photos[self.thumbnails.currentRow()].width} × {self.photos[self.thumbnails.currentRow()].height} px")
        self.export_value.setText(f"{self.workspace.output_width} × {self.workspace.output_height} px")
        self.statusBar().showMessage(t("loading_photo") if self.canvas.loading else t("status_loaded", count=len(self.photos)) if self.photos else t("status_empty"))
        self._refresh_controls()
