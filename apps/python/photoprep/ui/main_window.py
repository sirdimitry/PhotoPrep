"""PhotoPrep workspace: read-only photos, sessions, navigation and history.

Local AI previews run in isolated processes. Original image files stay read-only.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from collections import OrderedDict

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImageReader, QPixmap, QKeySequence, QAction
from PySide6.QtWidgets import (
    QFrame, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget, QButtonGroup, QSlider, QCheckBox,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget, QScrollArea, QComboBox,
)

from .. import __version__
from ..diagnostics import event
from ..i18n import tr
from ..models import Photo, list_folder_images
from ..settings import Preferences
from ..workspace import Workspace, ViewState
from ..editing import PhotoEdits, render_mask
from ..branding import LogoPlacement, read_logo, placement_from_path, template_catalog
from ..session import load_session, save_session, SessionError
from .assets import app_icon_path, icon_path, ui_icon, reset_icon
from .editor import EditorCanvas as PhotoCanvas
from .preferences_dialog import PreferencesDialog
from .theme import stylesheet
from .filmstrip import FilmstripDelegate
from .widgets import PhotoNameLabel, ToolOptions
from .ai_controller import AIController
from .export_dialog import ExportDialog
from ..inference import model_path, model_present
from ..catalog import get_model


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
        self.title.setStyleSheet("font-size:22px;font-weight:750;background:transparent;border:0")
        inner.addWidget(self.title)
        self.hint = QLabel()
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Muted")
        self.hint.setStyleSheet("background:transparent; border:0")
        inner.addWidget(self.hint)
        self.open_button = QPushButton()
        self.open_button.setObjectName("Primary")
        self.open_button.setMinimumHeight(40)
        self.open_button.clicked.connect(open_callback)
        inner.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.formats = QLabel()
        self.formats.setObjectName("SmallHint")
        self.formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.formats.setStyleSheet("background:transparent; border:0")
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
        self._previews = OrderedDict()
        self.ai = AIController(self)
        self.ai.changed.connect(self._refresh_controls)
        self.ai.progress.connect(self._ai_progress)
        self.ai.completed.connect(self._ai_completed)
        self.ai.failed.connect(self._ai_failed)
        self.ai.cancelled.connect(self._ai_cancelled)
        self._ai_stage = None
        self._ai_percent = 0
        self._after_view=False
        self._start_mask_on_load=None
        self._last_logo_placement=None
        self._export_dialog=None
        self.setWindowTitle("PhotoPrep")
        self.setWindowIcon(QIcon(app_icon_path()))
        self.setStyleSheet(stylesheet(self.settings.appearance))
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
        self._apply_appearance()
        self.retranslate()

    @property
    def photos(self):
        return self.workspace.photos

    def t(self, key: str, **data) -> str:
        return tr(self.settings.language, key, **data)

    def _tool_button(self, icon: str, label: str = "", *, rail: bool = False) -> QToolButton:
        button = QToolButton()
        button.setIcon(QIcon(icon_path(icon)))
        button.setProperty("iconName",icon)
        button.setIconSize(QSize(21,21) if rail else QSize(16,16))
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
        self.export_button.clicked.connect(self.open_export)
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
        for key, icon in [("mask", "brush"), ("erase", "eraser"), ("crop", "crop"),
                          ("select", "move"), ("logo", "logo"), ("compare", "compare")]:
            button = self._tool_button(icon, rail=True)
            button.setToolTip(key)
            if key in ("select", "mask", "erase", "crop", "logo"):
                button.setCheckable(True)
                self.tool_group.addButton(button)
                button.setChecked(key == "select")
                button.toggled.connect(lambda checked, tool=key: self._select_tool(tool) if checked else None)
            button.setEnabled(key == "select")
            self.tools[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        self.tools["compare"].setCheckable(True)
        self.tools["compare"].clicked.connect(lambda:self._compare_view(not self._after_view))
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
        self.thumbnails.setGridSize(QSize(140, 96))
        self.filmstrip_delegate = FilmstripDelegate(self.settings.appearance,self.thumbnails)
        self.thumbnails.setItemDelegate(self.filmstrip_delegate)
        self.thumbnails.setMouseTracking(True)
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
        button.setProperty("iconName",icon)
        button.setIconSize(QSize(16,16))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setFixedHeight(28)
        button.clicked.connect(callback)
        return button

    def _build_tool_options(self):
        options=ToolOptions()
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
        options.addWidget(self._build_logo_options())
        options.setVisible(False)
        return options

    def _select_tool(self, tool):
        if self.ai.busy:
            return
        if not self.tools[tool].isChecked():
            self.tools[tool].setChecked(True)
            return
        self._capture_view()
        self.canvas.set_tool(tool)
        if tool in ("mask","erase","crop","logo"):
            self._show_preview(True)
        self.tool_options.setCurrentIndex(2 if tool=="logo" else 1 if tool=="crop" else 0)
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
            self._show_preview(True)
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
        panel.setObjectName("InspectorShell")
        panel.setMinimumWidth(242)
        panel.setMaximumWidth(340)
        outer=QVBoxLayout(panel);outer.setContentsMargins(0,0,0,0)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content=QWidget();content.setObjectName('Inspector')
        content.setStyleSheet('QWidget#Inspector { border-left: 0; }')
        scroll.setWidget(content);outer.addWidget(scroll)
        layout = QVBoxLayout(content)
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
        ai_divider = QFrame()
        ai_divider.setObjectName('Divider')
        layout.addWidget(ai_divider)
        row = QHBoxLayout()
        self.process_button = QPushButton()
        self.process_button.setObjectName('Primary')
        self.process_button.setProperty('compact',True)
        self.process_button.setFixedHeight(30)
        self.process_button.clicked.connect(self._process_mask)
        row.addWidget(self.process_button,stretch=1)
        self.cancel_ai_button = QPushButton()
        self.cancel_ai_button.setProperty('compact',True)
        self.cancel_ai_button.setFixedHeight(30)
        self.cancel_ai_button.clicked.connect(self._cancel_ai)
        self.cancel_ai_button.hide()
        row.addWidget(self.cancel_ai_button)
        self.revert_ai_button = QToolButton()
        self.revert_ai_button.setObjectName("HeaderButton")
        self.revert_ai_button.setFixedSize(30,30)
        self.revert_ai_button.setIconSize(QSize(20,20))
        self.revert_ai_button.clicked.connect(self._revert_removal)
        row.addWidget(self.revert_ai_button)
        layout.addLayout(row)
        self.ai_status = QLabel()
        self.ai_status.setObjectName('SmallHint')
        self.ai_status.setWordWrap(True)
        layout.addWidget(self.ai_status)
        layout.addStretch(1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("SmallHint")
        layout.addWidget(self.note)
        return panel

    def _build_logo_options(self):
        panel=QWidget();layout=QVBoxLayout(panel);layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        row=QHBoxLayout();row.setSpacing(6)
        self.logo_choose=QPushButton();self.logo_last=QPushButton()
        for button in (self.logo_choose,self.logo_last):
            button.setProperty('compact',True);button.setFixedHeight(28);row.addWidget(button)
        self.logo_choose.clicked.connect(self._choose_logo);self.logo_last.clicked.connect(self._use_last_logo)
        self.logo_remove=self._compact_tool_button('close',lambda:self._set_logo(None));self.logo_remove.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.logo_remove.setFixedSize(28,28);row.addWidget(self.logo_remove);layout.addLayout(row)
        row=QHBoxLayout();row.setSpacing(6)
        self.logo_folder=QPushButton();self.logo_folder.setProperty('compact',True);self.logo_folder.setFixedHeight(28)
        self.logo_folder.clicked.connect(self._choose_logo_folder);row.addWidget(self.logo_folder)
        self.logo_library=QComboBox();self.logo_library.setMinimumWidth(0);self.logo_library.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.logo_library.setMinimumContentsLength(12);self.logo_library.setMaximumWidth(200)
        self.logo_library.activated.connect(self._choose_catalog_logo);row.addWidget(self.logo_library,stretch=1);layout.addLayout(row)
        self._load_logo_catalog()
        self.logo_empty=QLabel();self.logo_empty.setWordWrap(True);self.logo_empty.setObjectName('SmallHint');layout.addWidget(self.logo_empty)
        self.logo_details=QWidget();details=QVBoxLayout(self.logo_details);details.setContentsMargins(0,0,0,0);details.setSpacing(8)
        outer_layout=layout;layout=details
        self.logo_mode=QComboBox();self.logo_mode.currentIndexChanged.connect(self._logo_mode_changed);layout.addWidget(self.logo_mode)
        self.logo_name=PhotoNameLabel();self.logo_name.setObjectName('SmallHint');layout.addWidget(self.logo_name)
        for key,low,high in (('size',1,94),('opacity',0,100)):
            row=QHBoxLayout();row.setSpacing(4)
            label=QLabel();label.setFixedWidth(72)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(low,high);slider.setTracking(False);slider.setMinimumWidth(50);slider.setMaximumWidth(110)
            value=QLabel();value.setFixedWidth(34);value.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
            setattr(self,'logo_'+key+'_label',label);setattr(self,'logo_'+key,slider);setattr(self,'logo_'+key+'_value',value)
            slider.valueChanged.connect(lambda number,field=key:self._logo_adjust(field,number))
            row.addWidget(label);row.addWidget(slider,stretch=1);row.addWidget(value);layout.addLayout(row)
        row=QHBoxLayout();row.setSpacing(4);self.logo_positions=[]
        for symbol,key,x,y in (('↖','logo_tl',0,0),('↗','logo_tr',1,0),('⊙','logo_center',.5,.5),('↙','logo_bl',0,1),('↘','logo_br',1,1)):
            button=QToolButton();button.setText(symbol);button.setObjectName('CompactAction');button.setFixedSize(28,28)
            button.clicked.connect(lambda checked=False,a=x,b=y:self._logo_position(a,b));row.addWidget(button);self.logo_positions.append((button,key))
        row.addStretch(1);layout.addLayout(row)
        row=QHBoxLayout();self.logo_enabled=QCheckBox();self.logo_enabled.toggled.connect(lambda checked:self._logo_adjust('enabled',checked));row.addWidget(self.logo_enabled)
        layout.addLayout(row)
        outer_layout.addWidget(self.logo_details)
        self.logo_all=QPushButton();self.logo_all.setProperty('compact',True);self.logo_all.setFixedHeight(28);self.logo_all.clicked.connect(self._logo_apply_all);outer_layout.addWidget(self.logo_all)
        layout=outer_layout
        self.logo_hint=QLabel();self.logo_hint.setWordWrap(True);self.logo_hint.setObjectName('SmallHint');layout.addWidget(self.logo_hint)
        return panel

    def _has_logo(self):
        logo=self.workspace.edits.get(self.workspace.selected,PhotoEdits()).logo
        return bool(logo and logo.enabled and logo.opacity>0 and self.canvas._logo_image is not None)

    def _compare_view(self,after):
        if not after and self.canvas.tool!='select':
            self._select_tool('select')
        self._show_preview(after)

    def _choose_logo(self):
        path,_=QFileDialog.getOpenFileName(self,self.t('logo_choose_title'),self.settings.logo_path or str(Path.home()),'PNG (*.png)')
        if path:self._apply_logo_path(path)

    def _choose_logo_folder(self):
        folder=QFileDialog.getExistingDirectory(self,self.t('logo_folder_title'),self.settings.logo_folder or str(Path.home()))
        if folder:
            self.settings.logo_folder=folder;self._load_logo_catalog()
            if self.logo_library.count()>1:
                self.logo_library.setCurrentIndex(1);self._choose_catalog_logo(1)

    def _load_logo_catalog(self):
        self.logo_library.blockSignals(True);self.logo_library.clear()
        self.logo_library.addItem(self.t('logo_library'),'')
        try:entries=template_catalog(self.settings.logo_folder) if self.settings.logo_folder else []
        except OSError:entries=[]
        seen=set()
        for index,(group,label,path) in enumerate(entries):
            primary=self.t('logo_primary_left' if group==0 else 'logo_primary_right') if group<2 and group not in seen else label
            seen.add(group)
            self.logo_library.addItem(primary,str(path))
            self.logo_library.setItemData(index+1,label,Qt.ItemDataRole.ToolTipRole)
        self.logo_library.blockSignals(False)

    def _choose_catalog_logo(self,index):
        path=self.logo_library.itemData(index)
        if path:self._apply_logo_path(path)

    def _logo_mode_changed(self,index):
        logo=self.workspace.edits.get(self.workspace.selected,PhotoEdits()).logo
        if logo:
            try:placement=placement_from_path(logo.path,self.logo_mode.currentData())
            except (OSError,ValueError):return
            self._set_logo(replace(placement,opacity=logo.opacity,enabled=logo.enabled))

    def _use_last_logo(self):
        if self.settings.logo_path:self._apply_logo_path(self.settings.logo_path)

    def _apply_logo_path(self,path):
        if not self.canvas.has_photo or self.ai.busy:return
        try:placement=placement_from_path(path)
        except (OSError,ValueError):
            QMessageBox.warning(self,'PhotoPrep',self.t('logo_invalid'));return
        path=str(Path(path).resolve());self.settings.logo_path=path
        self._set_logo(placement)

    def _set_logo(self,logo):
        if not self.canvas.has_photo or self.ai.busy:return
        self._capture_view()
        edits=replace(self.workspace.edits.get(self.workspace.selected,PhotoEdits()),logo=logo)
        if self.workspace.set_edits(self.workspace.selected,edits):
            self.canvas.set_edits(edits);self._update_title()
        if logo:
            self._last_logo_placement=logo
            self._show_preview(True)
        self._refresh_controls()

    def _logo_adjust(self,field,value):
        logo=self.workspace.edits.get(self.workspace.selected,PhotoEdits()).logo
        if logo:
            field='width' if field=='size' else field
            self._set_logo(replace(logo,**{field:value if field=='enabled' else value/100}))

    def _logo_position(self,x,y):
        logo=self.workspace.edits.get(self.workspace.selected,PhotoEdits()).logo
        if logo:self._set_logo(replace(logo,x=x,y=y))

    def _logo_for_collection(self):
        return self.workspace.edits.get(self.workspace.selected,PhotoEdits()).logo or self._last_logo_placement

    def _logo_apply_all(self):
        if not self.canvas.has_photo or self.ai.busy:return
        self._capture_view()
        logo=self._logo_for_collection()
        try:
            if logo is None:
                if not self.settings.logo_path:return
                logo=placement_from_path(self.settings.logo_path)
            read_logo(logo.path,logo.mode)
        except (OSError,ValueError):
            QMessageBox.warning(self,'PhotoPrep',self.t('logo_invalid'));return
        logo=replace(logo,enabled=True,opacity=logo.opacity if logo.opacity>0 else 1.)
        self.workspace.set_logo_for_all(logo)
        self._last_logo_placement=logo
        self.canvas.set_edits(self.workspace.edits[self.workspace.selected])
        self._show_preview(True)
        self._update_title();self._refresh_controls()

    def _refresh_logo_controls(self,enabled):
        logo=self.workspace.edits.get(self.workspace.selected,PhotoEdits()).logo
        if logo:self._last_logo_placement=logo
        self.logo_details.setVisible(logo is not None)
        self.logo_empty.setVisible(logo is None)
        self.logo_empty.setText(self.t('logo_not_applied'))
        self.logo_hint.setVisible(logo is not None)
        self.logo_library.blockSignals(True)
        self.logo_library.setCurrentIndex(max(0,self.logo_library.findData(logo.path)) if logo else 0)
        self.logo_library.blockSignals(False)
        self.logo_folder.setEnabled(not self.ai.busy)
        self.logo_library.setEnabled(enabled and self.logo_library.count()>1)
        self.logo_mode.blockSignals(True)
        self.logo_mode.setCurrentIndex(self.logo_mode.findData(logo.mode if logo else 'logo'))
        self.logo_mode.setEnabled(enabled and logo is not None);self.logo_mode.blockSignals(False)
        self.logo_choose.setEnabled(enabled)
        self.logo_last.setEnabled(enabled and bool(self.settings.logo_path) and Path(self.settings.logo_path).is_file())
        self.logo_remove.setEnabled(enabled and logo is not None)
        candidate=self._logo_for_collection()
        candidate_path=candidate.path if candidate else self.settings.logo_path
        self.logo_all.setEnabled(enabled and bool(candidate_path) and Path(candidate_path).is_file())
        self.logo_enabled.blockSignals(True);self.logo_enabled.setChecked(bool(logo and logo.enabled));self.logo_enabled.setEnabled(enabled and logo is not None);self.logo_enabled.blockSignals(False)
        self.logo_name.set_filename(Path(logo.path).name if logo else self.t('logo_none'))
        self.logo_name.setToolTip(logo.path if logo else '')
        for field,number in (('size',round(logo.width*100) if logo else 15),('opacity',round(logo.opacity*100) if logo else 100)):
            slider=getattr(self,'logo_'+field);slider.blockSignals(True);slider.setValue(number);slider.setEnabled(enabled and bool(logo and logo.enabled));slider.blockSignals(False)
            getattr(self,'logo_'+field+'_value').setText(f'{number}%')
        for button,key in self.logo_positions:button.setEnabled(enabled and bool(logo and logo.enabled))

    def open_export(self):
        if self.ai.busy or not self.canvas.has_photo:return
        self._capture_view()
        dialog=ExportDialog(self.workspace,self.settings,self)
        self._export_dialog=dialog
        dialog.exec()
        self._export_dialog=None

    def _preview_key(self,edits=None):
        path = self.workspace.selected
        if not path:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        edits = edits or self.workspace.edits.get(path,PhotoEdits())
        return path,stat.st_mtime_ns,stat.st_size,edits.passes,edits.models_for_passes

    def _job_key(self):
        return self._preview_key(),self.workspace.edits.get(self.workspace.selected,PhotoEdits()).strokes,self.settings.model_id

    def _current_preview(self):
        return self._previews.get(self._preview_key())

    def _show_preview(self,after):
        if not self.canvas.has_photo:
            return
        image = self._current_preview() if after else None
        self._after_view=after
        self.canvas.set_preview(image)
        self.canvas.set_logo_visible(after and self.canvas.tool not in ("mask","erase"))
        self.canvas.set_comparison_before(not after)
        self.tools['compare'].setChecked(after)
        self.tools['compare'].setToolTip(self.t('compare_original' if after else 'compare_result'))
        self.tools['compare'].setAccessibleName(self.tools['compare'].toolTip())

    def _process_mask(self):
        if self.ai.busy or not self.canvas.has_photo:
            return
        self._capture_view()
        edits = self.workspace.edits.get(self.workspace.selected,PhotoEdits())
        if not edits.strokes and (not edits.passes or self._current_preview() is not None):
            return
        if edits.strokes and len(edits.passes)>=100:
            self._ai_failed("ai_pass_limit")
            return
        photo = self.photos[self.workspace.index]
        if photo.width*photo.height>40_000_000:
            self._ai_failed('inference_image_large')
            return
        mask = render_mask(photo.width,photo.height,edits.strokes) if edits.strokes else None
        # An erased mask can have strokes but no remaining painted pixels.
        if mask is not None and mask.constBits().tobytes().count(b'\x00')==mask.sizeInBytes():
            self._ai_failed('empty_mask')
            return
        self._ai_return_tool = self.canvas.tool
        base = self._current_preview()
        self._show_preview(base is not None)
        self._select_tool('select')
        self.ai.start(photo.path,mask,self._job_key(),base_image=base,replay=edits.passes if base is None else (),model_id=self.settings.model_id,replay_models=edits.models_for_passes if base is None else ())

    def _revert_removal(self):
        if self.ai.busy or not self.canvas.has_photo:
            return
        self._capture_view()
        path = self.workspace.selected
        edits = self.workspace.edits.get(path,PhotoEdits())
        if not edits.passes:
            return
        # Preserve later crop/logo changes and any newly drawn refinement strokes.
        edits = replace(edits,passes=edits.passes[:-1],
                        pass_models=edits.models_for_passes[:-1],
                        strokes=edits.passes[-1]+edits.strokes)
        self.canvas.set_edits(edits)
        self._edits_committed(path,edits)
        self._select_tool("mask")
        self.statusBar().showMessage(self.t("ai_reverted"),6000)

    def _cancel_ai(self):
        self._ai_stage = 'cancelled'
        self.ai.cancel()

    def _ai_progress(self,stage,percent):
        self._ai_stage,self._ai_percent = stage,percent
        self.ai_status.setText(self.t('ai_'+stage,percent=percent,name=get_model(self.ai._download_id or self.settings.model_id).name))

    def _ai_completed(self,key,image):
        self._ai_stage = None
        if key!=self._job_key() or not self.canvas.has_photo:
            return
        edits = self.workspace.edits.get(self.workspace.selected,PhotoEdits())
        if edits.strokes:
            edits = replace(edits,strokes=(),passes=edits.passes+(edits.strokes,),pass_models=edits.models_for_passes+(self.settings.model_id,))
            self.workspace.set_edits(self.workspace.selected,edits)
            self.canvas.set_edits(edits)
        key = self._preview_key()
        self._previews[key] = image
        self._previews.move_to_end(key)
        while sum(image.sizeInBytes() for image in self._previews.values())>192*1024*1024:
            self._previews.popitem(last=False)
        self._show_preview(True)
        if getattr(self,'_ai_return_tool','select') in ('mask','erase'):
            self._select_tool(self._ai_return_tool)
        self._refresh_controls()
        self._update_title()
        self.statusBar().showMessage(self.t('ai_refine_ready',count=len(edits.passes)),6000)

    def _ai_cancelled(self):
        self._ai_stage = 'cancelled'
        if getattr(self,'_ai_return_tool','select') in ('mask','erase'):
            self._select_tool(self._ai_return_tool)

    def _ai_failed(self,error):
        self._ai_stage = None
        if not self.ai.busy and self.canvas.tool=='select' and getattr(self,'_ai_return_tool','select') in ('mask','erase'):
            self._select_tool(self._ai_return_tool)
        QMessageBox.warning(self,'PhotoPrep',self.t(error))

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
        action(self.file_menu,"export",self.open_export,"Ctrl+Shift+E")
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
        for key, shortcut in (("select","V"),("mask","B"),("erase","E"),("crop","C"),("logo","L")):
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
        if self.ai.busy:
            return
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
            self._start_mask_on_load=self.workspace.selected
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
        self.canvas.set_output_dimensions(self.workspace.output_width,self.workspace.output_height)
        self.thumbnails.blockSignals(True)
        try:
            self.thumbnails.clear()
            for photo in self.photos:
                item = QListWidgetItem(self._thumbnail(photo) or QIcon(), photo.path.name)
                item.setToolTip(str(photo.path))
                item.setSizeHint(QSize(140, 96))
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
        if self.ai.busy:
            return
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
            self.canvas.set_output_dimensions(self.workspace.output_width,self.workspace.output_height)
            self.canvas.set_edits(self.workspace.edits.get(Path(path), PhotoEdits()))
        if success:
            edits=self.workspace.edits.get(Path(path),PhotoEdits())
            self._show_preview(bool(edits.strokes or edits.passes or edits.crop or edits.logo))
            if self._start_mask_on_load==Path(path):
                self._start_mask_on_load=None
                self._select_tool('mask')
        self._refresh_controls()
        self.statusBar().showMessage(self.t("status_loaded", count=len(self.photos)) if success
                                     else self.t("invalid_image", path=Path(path).name))

    def navigate(self, delta):
        index = self.workspace.index + delta
        if 0 <= index < len(self.photos):
            self.thumbnails.setCurrentRow(index)

    def remove_photo(self):
        if self.ai.busy:
            return
        self._capture_view()
        if self.workspace.remove_selected():
            self._present_workspace()
            self.statusBar().showMessage(self.t("removed_from_workspace"), 6000)

    def undo(self):
        if self.ai.busy:
            return
        self._capture_view()
        if self.workspace.undo():
            self._present_workspace()

    def redo(self):
        if self.ai.busy:
            return
        self._capture_view()
        if self.workspace.redo():
            self._present_workspace()

    def new_workspace(self):
        if self.ai.busy:
            return
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
        if self.ai.busy:
            return
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

    def shutdown(self):
        self.ai.shutdown()
        if self._export_dialog:self._export_dialog._shutdown()
        self.canvas.clear_photo()
        self.canvas._pool.waitForDone(5000)

    def closeEvent(self, event):
        from ..diagnostics import event as record
        record('window_close_requested',unsaved=self.workspace.dirty,worker_active=self.ai.busy)
        if self._confirm_discard():
            self.shutdown()
            event.accept()
        else:
            event.ignore()

    def _update_info(self, photo: Photo):
        self.photo_label.set_filename(photo.path.name)
        self.source_value.setText(f"{photo.width} × {photo.height} px")
        self.export_value.setText(f"{self.workspace.output_width} × {self.workspace.output_height} px")

    def _refresh_controls(self):
        enabled = self.canvas.has_photo and not self.ai.busy
        for button in (self.fit_button, self.actual_button, self.zoom_in_button, self.zoom_out_button):
            button.setEnabled(enabled)
        index = self.workspace.index
        self.previous_button.setEnabled(index > 0 and not self.ai.busy)
        self.next_button.setEnabled(0 <= index < len(self.photos) - 1 and not self.ai.busy)
        self.remove_button.setEnabled(index >= 0 and not self.ai.busy)
        for tool in ("mask","erase","crop","logo"):
            self.tools[tool].setEnabled(enabled)
        self.tool_options.setEnabled(enabled)
        edits = self.workspace.edits.get(self.workspace.selected,PhotoEdits())
        preview = self._current_preview() is not None
        has_result=preview or bool(edits.strokes or edits.passes or edits.crop or edits.logo) or (self.workspace.output_width,self.workspace.output_height)!=(1136,710)
        self.tools['compare'].setEnabled(enabled and has_result)
        self.export_button.setEnabled(enabled)
        self._refresh_logo_controls(enabled)
        self.process_button.setEnabled(enabled and (bool(edits.strokes) or (bool(edits.passes) and not preview)))
        self.process_button.setText(self.t('ai_restore' if edits.passes and not preview and not edits.strokes else 'process_mask'))
        spec = get_model(self.settings.model_id)
        self.process_button.setToolTip(self.t('ai_download_hint',name=spec.name,size=f'{spec.size/1e6:.1f}') if not model_present(model_path(self.settings.model_id),self.settings.model_id) else self.t('ai_model_active',name=spec.name))
        self.revert_ai_button.setVisible(bool(edits.passes))
        self.revert_ai_button.setEnabled(enabled and bool(edits.passes))
        self.cancel_ai_button.setVisible(self.ai.busy)
        for widget in (self.thumbnails,self.open_files_button,self.open_folder_button,self.settings_button):
            widget.setEnabled(not self.ai.busy)
        if not self.ai.busy:
            if self._ai_stage=='cancelled':
                status = self.t('ai_cancelled')
            elif preview:
                status = self.t('ai_refine_ready',count=len(edits.passes))
            else:
                status = self.t('ai_restore_hint' if edits.passes else 'ai_ready')
            self.ai_status.setText(status)
        self.clear_mask_button.setEnabled(enabled and bool(edits.strokes))
        self.clear_crop_button.setEnabled(enabled and edits.crop is not None)
        self.reset_crop_button.setEnabled(enabled)
        self.fit_crop_button.setEnabled(enabled)
        self.photo_position.setText(self.t("images_loaded", index=index + 1, total=len(self.photos)) if self.photos else "")
        if hasattr(self, "actions"):
            self.actions["export"].setEnabled(enabled)
            self.actions["undo"].setEnabled(self.workspace.can_undo and not self.ai.busy)
            self.actions["redo"].setEnabled(self.workspace.can_redo and not self.ai.busy)
            for key in ("open_photos","open_folder","new_workspace","open_workspace","save_workspace","save_workspace_as"):
                self.actions[key].setEnabled(not self.ai.busy)
            self.actions["remove_photo"].setEnabled(index >= 0 and not self.ai.busy)
            self.actions["previous_photo"].setEnabled(index > 0 and not self.ai.busy)
            self.actions["next_photo"].setEnabled(0 <= index < len(self.photos) - 1 and not self.ai.busy)
            for key in ("fit", "actual", "zoom_in", "zoom_out", "mask", "erase", "crop", "logo", "brush_smaller", "brush_larger"):
                self.actions[key].setEnabled(enabled)

    def open_settings(self):
        if self.ai.busy:
            return
        dialog = PreferencesDialog(self.settings, self, dimensions=(self.workspace.output_width,self.workspace.output_height))
        dialog.applied.connect(self._preferences_applied)
        dialog.exec()
        self._refresh_controls()

    def _apply_appearance(self):
        appearance = self.settings.appearance
        self.revert_ai_button.setIcon(reset_icon(appearance))
        self.setStyleSheet(stylesheet(appearance))
        self.canvas.set_appearance(appearance)
        self.filmstrip_delegate.appearance = appearance
        self.thumbnails.viewport().update()
        for button in self.findChildren(QToolButton):
            name = button.property('iconName')
            if name and button not in (self.previous_button,self.next_button):
                button.setIcon(ui_icon(name,appearance))
        for button,name in ((self.open_files_button,'files'),(self.open_folder_button,'folder'),(self.export_button,'export')):
            button.setIcon(ui_icon(name,appearance,button.objectName()=='Primary'))

    def _preferences_applied(self):
        self._capture_view()
        changed=(self.workspace.output_width,self.workspace.output_height)!=(self.settings.output_width,self.settings.output_height)
        self.workspace.set_output_size(self.settings.output_width,self.settings.output_height)
        self._apply_appearance()
        self.canvas.set_output_dimensions(self.workspace.output_width,self.workspace.output_height)
        if self.workspace.selected:
            self.canvas.set_edits(self.workspace.edits.get(self.workspace.selected,PhotoEdits()))
            if changed:self._show_preview(True)
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
        self.logo_choose.setText(t('logo_choose'))
        self.logo_folder.setText(t('logo_folder'))
        self.logo_folder.setToolTip(t('logo_folder_title'))
        selected_template=self.logo_library.currentData()
        self._load_logo_catalog()
        self.logo_library.setCurrentIndex(max(0,self.logo_library.findData(selected_template)))
        self.logo_mode.blockSignals(True)
        mode=self.logo_mode.currentData() or 'logo';self.logo_mode.clear()
        for key in ('template','logo'):self.logo_mode.addItem(t('logo_mode_'+key),key)
        self.logo_mode.setCurrentIndex(self.logo_mode.findData(mode));self.logo_mode.blockSignals(False)
        self.logo_last.setText(t('logo_last'))
        self.logo_remove.setToolTip(t('logo_remove'))
        self.logo_enabled.setText(t('logo_enabled'))
        self.logo_all.setText(t('logo_all'))
        self.logo_size_label.setText(t('logo_size'))
        self.logo_opacity_label.setText(t('logo_opacity'))
        self.logo_hint.setText(t('logo_hint'))
        for button,key in self.logo_positions:
            button.setToolTip(t(key));button.setAccessibleName(t(key))
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
        self.export_button.setToolTip(t("export_note"))
        self.settings_button.setToolTip(t("settings"))
        self.photo_label.set_filename(self.photos[self.thumbnails.currentRow()].path.name if self.photos and self.thumbnails.currentRow() >= 0 else "")
        self.fit_button.setText(t("fit"))
        self.actual_button.setText(t("actual"))
        self.zoom_in_button.setToolTip(t("zoom_in"))
        self.zoom_out_button.setToolTip(t("zoom_out"))
        for key, button in self.tools.items():
            button.setToolTip(t(key) + (" · " + t("coming_soon") if key not in ("select","mask","erase","crop","logo","compare") else ""))
        self.empty.retranslate(t)
        self.strip_title.setText(f'{t("photos")}  ·  {len(self.photos)}')
        self.inspector_label.setText(t("inspect"))
        self.image_heading.setText(t("image"))
        self.source_title.setText(t("source_size"))
        self.export_title.setText(t("export_preset"))
        self.note.setText(t("ai_preview_note"))
        self.process_button.setText(t("process_mask"))
        self.cancel_ai_button.setText(t("ai_cancel"))
        self.revert_ai_button.setAccessibleName(t("ai_revert"))
        self.revert_ai_button.setToolTip(t("ai_revert")+"\n"+t("ai_revert_hint"))
        self.tools['compare'].setToolTip(t('compare_original' if self._after_view else 'compare_result'))
        self.tools['compare'].setAccessibleName(self.tools['compare'].toolTip())
        self.source_value.setText("—" if not self.photos or self.thumbnails.currentRow() < 0 else f"{self.photos[self.thumbnails.currentRow()].width} × {self.photos[self.thumbnails.currentRow()].height} px")
        self.export_value.setText(f"{self.workspace.output_width} × {self.workspace.output_height} px")
        self.statusBar().showMessage(t("loading_photo") if self.canvas.loading else t("status_loaded", count=len(self.photos)) if self.photos else t("status_empty"))
        self._refresh_controls()
