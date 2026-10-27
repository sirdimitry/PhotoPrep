"""Neutral graphite design language with a restrained yellow accent."""

STYLESHEET = """
QWidget { background: #1C1E22; color: #EBEDF0; font-family: -apple-system, 'SF Pro Text', 'Inter', sans-serif; font-size: 13px; }
QMainWindow { background: #1C1E22; }
QWidget#Header { background: #25272B; border-bottom: 1px solid #373A40; }
QWidget#ToolRail { background: #24262A; border-right: 1px solid #373A40; }
QWidget#Inspector { background: #24262A; border-left: 1px solid #383B41; }
QWidget#FilmstripPanel { background: #222428; border-top: 1px solid #363940; }
QWidget#Workspace { background: #14161A; }
QWidget#ImageBar { background: #1F2126; border-bottom: 1px solid #363940; }
QLabel#BrandName { font-size: 19px; font-weight: 750; letter-spacing: -0.4px; }
QLabel#SmallHint { color: #888D97; font-size: 11px; }
QLabel#SectionTitle { color: #F2F3F5; font-size: 12px; font-weight: 700; }
QLabel#Muted { color: #9DA2AC; }
QLabel#Value { color: #F2F3F5; font-weight: 600; }
QLabel#Badge { background: #3C3723; color: #E8C44F; border-radius: 7px; padding: 4px 8px; font-weight: 700; font-size: 10px; }
QFrame#Divider { background: #363940; max-height: 1px; min-height: 1px; }
QFrame#InfoCard { background: #2A2D32; border: 1px solid #393C42; border-radius: 9px; }
QPushButton, QToolButton { background: #30343A; color: #E6E9EC; border: 1px solid #41454D; border-radius: 8px; padding: 8px 11px; }
QPushButton:hover, QToolButton:hover { background: #40454D; border-color: #555B65; }
QPushButton:pressed, QToolButton:pressed { background: #4A505B; }
QPushButton:disabled, QToolButton:disabled { color: #6F737C; background: #292C31; border-color: #33363B; }
QPushButton#Primary { color: #1A1C20; background: #FACC15; border: 1px solid #FACC15; font-weight: 750; }
QPushButton#Primary:hover { background: #FBDC3E; }
QPushButton#Primary:disabled { background: #585136; color: #8A8160; border-color: #585136; }
QToolButton#RailButton { min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; padding: 3px; border: 0; background: transparent; }
QToolButton#RailButton:hover { background: #3B3F46; }
QToolButton#RailButton:checked { background: #48432B; border-left: 3px solid #FACC15; }
QToolButton#HeaderButton { background: transparent; border: 0; padding: 7px; }
QToolButton#HeaderButton:hover { background: #373B41; }
QListWidget { background: transparent; border: 0; outline: none; }
QListWidget::item { border-radius: 8px; background: #2B2E34; border: 2px solid transparent; padding: 5px; margin: 2px; }
QListWidget::item:selected { background: #35362B; border: 2px solid #FACC15; }
QListWidget::item:hover { background: #383C43; }
QScrollBar:horizontal, QScrollBar:vertical { background: #222428; border: 0; height: 9px; width: 9px; }
QScrollBar::handle:horizontal, QScrollBar::handle:vertical { background: #555A63; border-radius: 4px; min-width: 25px; min-height: 25px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QStatusBar { background: #25272B; color: #9EA2AC; border-top: 1px solid #363940; }
QDialog { background: #222428; }
QSpinBox, QComboBox { border: 1px solid #494C53; border-radius: 7px; background: #31353B; padding: 8px; min-height: 18px; }
QComboBox QAbstractItemView { background: #31353B; color: #EFF1F3; selection-background-color: #555138; }
QGroupBox { border: 1px solid #40434A; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 650; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QSplitter::handle { background: #31343A; width: 1px; }
QScrollArea { background: transparent; border: none; }
"""
