"""Neutral graphite design language with a restrained yellow accent."""

STYLESHEET = """
QWidget { background: #1C1E22; color: #EBEDF0; font-family: 'Helvetica Neue', 'Arial', sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QMainWindow { background: #1C1E22; }
QWidget#Header { background: #25272B; border-bottom: 1px solid #373A40; }
QWidget#ToolRail { background: #24262A; border-right: 1px solid #373A40; }
QWidget#Inspector { background: #24262A; border-left: 1px solid #383B41; }
QWidget#FilmstripPanel { background: #222428; border-top: 1px solid #363940; }
QWidget#Workspace { background: #14161A; }
QStackedWidget#ToolOptions, QStackedWidget#ToolOptions > QWidget { background: transparent; border: none; }
QSlider::groove:horizontal { height: 4px; background: #4B5059; border-radius: 2px; }
QSlider::handle:horizontal { background: #FACC15; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QWidget#ImageBar { background: #1F2126; border-bottom: 1px solid #363940; }
QLabel#BrandName { font-size: 17px; font-weight: 750; letter-spacing: -0.4px; }
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
QPushButton[compact="true"], QToolButton#CompactAction { min-height: 0; padding: 3px 7px; border-radius: 5px; font-size: 12px; }
QLabel#HeaderPhotoName { font-size: 12px; font-weight: 600; color: #C6CAD1; }
QPushButton#Primary { color: #1A1C20; background: #FACC15; border: 1px solid #FACC15; font-weight: 750; }
QPushButton#Primary:hover { background: #FBDC3E; }
QPushButton#Primary:disabled { background: #585136; color: #8A8160; border-color: #585136; }
QToolButton#RailButton { min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 3px; border: 0; background: transparent; }
QToolButton#RailButton:hover { background: #3B3F46; }
QToolButton#RailButton:checked { background: #48432B; border-left: 3px solid #FACC15; }
QToolButton#HeaderButton { background: transparent; border: 0; padding: 4px; }
QToolButton#HeaderButton:hover { background: #373B41; }
QListWidget { background: transparent; border: 0; outline: none; }
QScrollBar:horizontal, QScrollBar:vertical { background: #222428; border: 0; height: 9px; width: 9px; }
QScrollBar::handle:horizontal, QScrollBar::handle:vertical { background: #555A63; border-radius: 4px; min-width: 25px; min-height: 25px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QStatusBar { background: #25272B; color: #9EA2AC; border-top: 1px solid #363940; }
QDialog { background: #222428; }
QSpinBox, QComboBox { border: 1px solid #494C53; border-radius: 7px; background: #31353B; padding: 8px; min-height: 18px; }
QComboBox QAbstractItemView { background: #31353B; color: #EFF1F3; selection-background-color: #555138; }
QPushButton#LanguageChoice:checked { background: #48432B; color: #FACC15; border: 1px solid #FACC15; }
QToolButton#SettingsDisclosure { background: transparent; border: none; padding: 8px 0; text-align: left; }
QFrame#SettingsCard { background: #292C31; border: 1px solid #3D424A; border-radius: 9px; }
QLineEdit#DimensionInput { color: #EBEDF0; min-height: 40px; background: #34383F; border: 1px solid #535963; padding: 0; border-radius: 7px; }
QLineEdit#DimensionInput:focus { border-color: #FACC15; }

QGroupBox { border: 1px solid #40434A; border-radius: 8px; margin-top: 12px; padding: 12px; font-weight: 650; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QSplitter::handle { background: #31343A; width: 1px; }
QScrollArea { background: transparent; border: none; }
QRadioButton::indicator { width: 12px; height: 12px; border: 1px solid #555B65; border-radius: 7px; background: #30343A; }
QRadioButton::indicator:checked { background: #FACC15; border-color: #FACC15; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: #30343A; color: #E6E9EC; border: 1px solid #41454D; padding: 7px 16px; }
QTabBar::tab:selected { background: #48432B; color: #FACC15; border-bottom: 2px solid #FACC15; }
QProgressBar { border: 1px solid #41454D; border-radius: 4px; background: #292C31; text-align: center; font-size: 10px; }
QProgressBar::chunk { background: #FACC15; border-radius: 3px; }
"""


# Replace each original colour once, so light colours cannot be remapped again.
LIGHT_COLORS = {
    '#1C1E22':'#F2F4F7', '#EBEDF0':'#26313F', '#25272B':'#FFFFFF',
    '#373A40':'#D5DAE1', '#24262A':'#F7F8FA', '#383B41':'#D5DAE1',
    '#222428':'#F1F3F6', '#363940':'#D5DAE1', '#14161A':'#E9EDF2',
    '#4B5059':'#BEC6D0', '#1F2126':'#F1F3F6', '#888D97':'#657181',
    '#F2F3F5':'#273240', '#9DA2AC':'#657181', '#3C3723':'#FFF3BA',
    '#E8C44F':'#806000', '#2A2D32':'#FFFFFF', '#393C42':'#D2D8E0',
    '#30343A':'#FFFFFF', '#E6E9EC':'#26313F', '#41454D':'#C8D0DA',
    '#40454D':'#E6EBF1', '#555B65':'#A9B4C1', '#4A505B':'#D7DFE8',
    '#6F737C':'#8C95A1', '#292C31':'#E9EDF2', '#33363B':'#DCE1E7',
    '#C6CAD1':'#4D5A6C', '#3B3F46':'#E5EAF0', '#48432B':'#FFF1B1',
    '#373B41':'#E5EAF0', '#555A63':'#ADB7C4', '#9EA2AC':'#657181',
    '#494C53':'#C8D0DA', '#31353B':'#FFFFFF', '#EFF1F3':'#26313F',
    '#555138':'#FFF1B1', '#3D424A':'#D0D7E0', '#34383F':'#FFFFFF',
    '#535963':'#B8C3D0', '#40434A':'#CCD4DE', '#31343A':'#D5DAE1',
}

def stylesheet(appearance='dark'):
    import re
    base = STYLESHEET + "\nQFrame#HeaderDivider { background: #373A40; }"
    if appearance == 'light':
        base = re.sub(r'#[0-9A-Fa-f]{6}',lambda match:LIGHT_COLORS.get(match[0],match[0]),base)
        base += "\nQPushButton#LanguageChoice:checked, QTabBar::tab:selected { color: #725500; }"
    return base
