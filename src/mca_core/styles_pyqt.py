"""
MCA Brain System - PyQt6 样式模块

提供简洁专业的配色方案和 CSS 样式生成。
"""

from __future__ import annotations

from typing import Optional


class ColorPalette:
    """配色方案类，定义浅色专业主题。"""

    LIGHT: dict[str, str] = {
        "bg": "#f5f6fa",
        "card_bg": "#ffffff",
        "text_primary": "#1a1a2e",
        "text_secondary": "#4a4a6a",
        "text_muted": "#8888a0",
        "accent": "#3b6ff5",
        "accent_hover": "#2952cc",
        "accent_light": "#dce4fd",
        "success": "#2ea043",
        "warning": "#d4a017",
        "error": "#d73a49",
        "info": "#3b6ff5",
        "border": "#d0d5dd",
        "input_bg": "#ffffff",
    }

    CURRENT: dict[str, str] = LIGHT


def generate_css(palette: Optional[dict[str, str]] = None) -> str:
    """根据配色方案生成完整的 CSS 样式表。"""
    if palette is None:
        palette = ColorPalette.CURRENT

    return f"""
/* ============================================================
   MCA Brain System - 专业简洁 UI 样式表
   ============================================================ */

* {{
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', system-ui, -apple-system, sans-serif;
    font-size: 13px;
    color: {palette['text_secondary']};
}}

QMainWindow, QWidget#mainContainer {{
    background: {palette['bg']};
}}

QFrame#siliconeCard {{
    background: {palette['card_bg']};
    border-radius: 8px;
    border: 1px solid {palette['border']};
}}

QLabel {{
    color: {palette['text_primary']};
    background: transparent;
}}

QLabel#titleLabel {{
    font-size: 20px;
    font-weight: bold;
    color: {palette['text_primary']};
}}

QLabel#subtitleLabel {{
    font-size: 12px;
    color: {palette['text_muted']};
}}

QLabel#accentLabel {{
    color: {palette['accent']};
    font-weight: 700;
    font-size: 14px;
}}

QPushButton {{
    background: {palette['card_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
    color: {palette['text_secondary']};
}}

QPushButton:hover {{
    background: {palette['accent_light']};
    border-color: {palette['accent']};
    color: {palette['text_primary']};
}}

QPushButton:pressed {{
    background: {palette['accent']};
    color: white;
}}

QPushButton:disabled {{
    color: {palette['text_muted']};
    background: {palette['bg']};
    border-color: {palette['border']};
}}

QPushButton#accentButton, QPushButton#primaryBtn {{
    background: {palette['accent']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#accentButton:hover, QPushButton#primaryBtn:hover {{
    background: {palette['accent_hover']};
}}

QPushButton#successBtn {{
    background: {palette['success']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#warningBtn {{
    background: {palette['warning']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#dangerBtn, QPushButton#errorBtn {{
    background: {palette['error']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#smallBtn {{
    padding: 4px 10px;
    font-size: 11px;
    border-radius: 4px;
    font-weight: 600;
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {palette['input_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 8px 10px;
    color: {palette['text_primary']};
    selection-background-color: {palette['accent_light']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {palette['accent']};
}}

QListWidget, QTreeWidget {{
    background: {palette['card_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 4px;
    color: {palette['text_primary']};
}}

QListWidget::item, QTreeWidget::item {{
    padding: 6px 10px;
    border-radius: 4px;
    margin: 2px 0;
}}

QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {palette['accent']};
    color: white;
}}

QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected {{
    background: {palette['accent_light']};
}}

QProgressBar {{
    background: {palette['bg']};
    border: 1px solid {palette['border']};
    border-radius: 4px;
    text-align: center;
    color: {palette['text_secondary']};
    height: 12px;
    font-weight: 600;
}}

QProgressBar::chunk {{
    background: {palette['accent']};
    border-radius: 3px;
}}

QComboBox {{
    background: {palette['input_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 8px 12px;
    color: {palette['text_primary']};
}}

QComboBox:hover {{
    border-color: {palette['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

QComboBox QAbstractItemView {{
    background: {palette['card_bg']};
    border: 1px solid {palette['border']};
    border-radius: 4px;
    selection-background-color: {palette['accent']};
    selection-color: white;
}}

QSpinBox, QDoubleSpinBox {{
    background: {palette['input_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {palette['text_primary']};
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {palette['accent']};
}}

QCheckBox {{
    spacing: 10px;
    color: {palette['text_primary']};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 3px;
    border: 2px solid {palette['border']};
    background: {palette['card_bg']};
}}

QCheckBox::indicator:checked {{
    background: {palette['accent']};
    border-color: {palette['accent']};
}}

QCheckBox::indicator:hover {{
    border-color: {palette['accent']};
}}

QRadioButton {{
    spacing: 10px;
    color: {palette['text_primary']};
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid {palette['border']};
    background: {palette['card_bg']};
}}

QRadioButton::indicator:checked {{
    background: {palette['accent']};
    border-color: {palette['accent']};
}}

QTabWidget::pane {{
    border: none;
    background: transparent;
}}

QTabBar::tab {{
    background: {palette['bg']};
    border: 1px solid {palette['border']};
    border-radius: 4px;
    padding: 8px 16px;
    margin-right: 4px;
    color: {palette['text_muted']};
    font-weight: 600;
}}

QTabBar::tab:selected {{
    background: {palette['card_bg']};
    color: {palette['accent']};
    border-bottom: 2px solid {palette['accent']};
}}

QTabBar::tab:hover:!selected {{
    background: {palette['accent_light']};
    color: {palette['text_primary']};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: {palette['border']};
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {palette['text_muted']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 4px;
}}

QScrollBar::handle:horizontal {{
    background: {palette['border']};
    border-radius: 4px;
    min-width: 30px;
}}

QSplitter::handle {{
    background: {palette['border']};
}}

QMenu {{
    background: {palette['card_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 8px 24px;
    border-radius: 4px;
    color: {palette['text_primary']};
}}

QMenu::item:selected {{
    background: {palette['accent']};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background: {palette['border']};
    margin: 4px 8px;
}}

QToolTip {{
    background: {palette['text_primary']};
    color: {palette['card_bg']};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 12px;
    border: 1px solid {palette['border']};
}}

QStatusBar {{
    background: {palette['card_bg']};
    color: {palette['text_muted']};
    border-top: 1px solid {palette['border']};
    padding: 4px;
}}

QGroupBox {{
    background: {palette['card_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 12px;
    margin-top: 8px;
    font-weight: 700;
    color: {palette['text_primary']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 3px 10px;
    color: {palette['text_primary']};
}}

QTextBrowser {{
    background: {palette['card_bg']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 10px;
    color: {palette['text_primary']};
    selection-background-color: {palette['accent_light']};
}}

QDialog {{
    background: {palette['bg']};
}}

QLabel#badgeSuccess {{
    background: {palette['success']};
    color: white;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#badgeWarning {{
    background: {palette['warning']};
    color: white;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#badgeError {{
    background: {palette['error']};
    color: white;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#badgeInfo {{
    background: {palette['info']};
    color: white;
    border-radius: 3px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}}
"""


CSS: str = generate_css(ColorPalette.LIGHT)