"""
MCA Brain System - PyQt6 样式模块

提供简洁专业的配色方案、字体层级系统和 CSS 样式生成。
Type Scale: 11/12/13/14/16/18/24  (caption / body-sm / body / body-lg / h3 / h2 / h1)
Spacing Scale: 4/6/8/10/12/16/20/24  (xs / sm / md / ml / lg / xl / xxl / xxxl)
"""

from __future__ import annotations

from typing import Optional


class ColorPalette:
    """配色方案类，定义浅色专业主题。

    色彩语义:
        bg          - 页面背景
        card_bg     - 卡片/容器背景
        text_primary - 主文字
        text_secondary - 次要文字
        text_muted  - 辅助/禁用文字
        accent      - 主强调色（按钮、链接、选中态）
        success     - 成功/正常
        warning     - 警告
        error       - 错误/危险
        border      - 边框/分割线
    """

    LIGHT: dict[str, str] = {
        "bg": "#f0f2f5",
        "card_bg": "#ffffff",
        "text_primary": "#1a1a2e",
        "text_secondary": "#4a4a6a",
        "text_muted": "#8b8ba8",
        "accent": "#3b6ff5",
        "accent_hover": "#2952cc",
        "accent_light": "#e8eeff",
        "success": "#2ea043",
        "success_light": "#e6f4ea",
        "warning": "#d4a017",
        "warning_light": "#fef7e0",
        "error": "#d73a49",
        "error_light": "#fce8ea",
        "info": "#3b6ff5",
        "border": "#e0e3eb",
        "border_light": "#f0f2f5",
        "input_bg": "#ffffff",
        "shadow": "rgba(0,0,0,0.04)",
    }

    CURRENT: dict[str, str] = LIGHT


def generate_css(palette: Optional[dict[str, str]] = None) -> str:
    """根据配色方案生成完整的 CSS 样式表。"""
    if palette is None:
        palette = ColorPalette.CURRENT

    P = palette  # shorthand

    return f"""
/* ============================================================
   MCA Brain System - 专业 UI 排版系统 v2
   Type Scale: 11/12/13/14/16/18/24
   Spacing: 4/6/8/10/12/16/20/24
   ============================================================ */

/* ----------------------------------------------------------
   全局基础
   ---------------------------------------------------------- */

* {{
    font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC',
                 system-ui, -apple-system, sans-serif;
    font-size: 13px;
    color: {P['text_secondary']};
}}

QMainWindow, QWidget#mainContainer {{
    background: {P['bg']};
}}

/* ----------------------------------------------------------
   卡片容器
   ---------------------------------------------------------- */

QFrame#siliconeCard {{
    background: {P['card_bg']};
    border-radius: 10px;
    border: 1px solid {P['border']};
}}

QFrame#siliconeCardFlat {{
    background: {P['card_bg']};
    border-radius: 10px;
    border: none;
}}

/* ----------------------------------------------------------
   排版层级 — Typography
   ---------------------------------------------------------- */

QLabel#h1 {{
    font-size: 24px;
    font-weight: 800;
    color: {P['text_primary']};
    letter-spacing: -0.5px;
}}

QLabel#h2 {{
    font-size: 18px;
    font-weight: 700;
    color: {P['text_primary']};
}}

QLabel#h3 {{
    font-size: 16px;
    font-weight: 700;
    color: {P['text_primary']};
}}

QLabel#body-lg {{
    font-size: 14px;
    font-weight: 600;
    color: {P['text_primary']};
}}

QLabel#body {{
    font-size: 13px;
    color: {P['text_secondary']};
}}

QLabel#body-sm {{
    font-size: 12px;
    color: {P['text_secondary']};
}}

QLabel#caption {{
    font-size: 11px;
    color: {P['text_muted']};
}}

QLabel#titleLabel {{
    font-size: 20px;
    font-weight: bold;
    color: {P['text_primary']};
}}

QLabel#subtitleLabel {{
    font-size: 12px;
    color: {P['text_muted']};
}}

QLabel#accentLabel {{
    color: {P['accent']};
    font-weight: 700;
    font-size: 14px;
}}

QLabel#sectionHeader {{
    font-size: 14px;
    font-weight: 700;
    color: {P['text_primary']};
    padding-bottom: 4px;
}}

/* ----------------------------------------------------------
   按钮 — Buttons
   ---------------------------------------------------------- */

QPushButton {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 13px;
    color: {P['text_secondary']};
    min-height: 32px;
}}

QPushButton:hover {{
    background: {P['accent_light']};
    border-color: {P['accent']};
    color: {P['text_primary']};
}}

QPushButton:pressed {{
    background: {P['accent']};
    color: white;
}}

QPushButton:disabled {{
    color: {P['text_muted']};
    background: {P['bg']};
    border-color: {P['border']};
}}

/* 工具栏按钮 — 更紧凑的无边框样式 */
QPushButton#toolbarBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 13px;
    color: {P['text_secondary']};
    min-height: 30px;
}}

QPushButton#toolbarBtn:hover {{
    background: {P['accent_light']};
    border-color: {P['border']};
    color: {P['text_primary']};
}}

QPushButton#toolbarBtn:pressed {{
    background: {P['accent']};
    color: white;
    border-color: {P['accent']};
}}

/* 主操作按钮 */
QPushButton#accentButton, QPushButton#primaryBtn {{
    background: {P['accent']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
    padding: 8px 20px;
    min-height: 34px;
}}

QPushButton#accentButton:hover, QPushButton#primaryBtn:hover {{
    background: {P['accent_hover']};
}}

QPushButton#accentButton:disabled, QPushButton#primaryBtn:disabled {{
    background: {P['border']};
    color: {P['text_muted']};
}}

QPushButton#successBtn {{
    background: {P['success']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#successBtn:hover {{
    background: #238636;
}}

QPushButton#warningBtn {{
    background: {P['warning']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#dangerBtn, QPushButton#errorBtn {{
    background: {P['error']};
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 700;
}}

QPushButton#smallBtn {{
    padding: 4px 10px;
    font-size: 12px;
    border-radius: 4px;
    font-weight: 600;
    min-height: 26px;
}}

/* ----------------------------------------------------------
   输入控件 — Inputs
   ---------------------------------------------------------- */

QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {P['input_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    padding: 8px 10px;
    color: {P['text_primary']};
    selection-background-color: {P['accent_light']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {P['accent']};
}}

QLineEdit {{
    min-height: 32px;
}}

/* ----------------------------------------------------------
   列表 / 树 — Lists & Trees
   ---------------------------------------------------------- */

QListWidget, QTreeWidget {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    padding: 4px;
    color: {P['text_primary']};
    outline: none;
}}

QListWidget::item, QTreeWidget::item {{
    padding: 6px 10px;
    border-radius: 4px;
    margin: 1px 0;
}}

QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {P['accent']};
    color: white;
}}

QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected {{
    background: {P['accent_light']};
}}

/* ----------------------------------------------------------
   表格 — Tables
   ---------------------------------------------------------- */

QTableWidget {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    gridline-color: {P['border_light']};
    outline: none;
}}

QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {P['border_light']};
}}

QTableWidget::item:selected {{
    background: {P['accent_light']};
    color: {P['text_primary']};
}}

QHeaderView::section {{
    background: {P['bg']};
    border: none;
    border-bottom: 2px solid {P['border']};
    padding: 8px 10px;
    font-weight: 700;
    font-size: 12px;
    color: {P['text_secondary']};
    text-transform: uppercase;
}}

QHeaderView::section:hover {{
    background: {P['accent_light']};
}}

/* ----------------------------------------------------------
   进度条 — Progress
   ---------------------------------------------------------- */

QProgressBar {{
    background: {P['bg']};
    border: 1px solid {P['border']};
    border-radius: 4px;
    text-align: center;
    color: {P['text_secondary']};
    height: 10px;
    font-weight: 600;
    font-size: 11px;
}}

QProgressBar::chunk {{
    background: {P['accent']};
    border-radius: 3px;
}}

/* ----------------------------------------------------------
   下拉框 — ComboBox
   ---------------------------------------------------------- */

QComboBox {{
    background: {P['input_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    padding: 7px 12px;
    color: {P['text_primary']};
    min-height: 32px;
}}

QComboBox:hover {{
    border-color: {P['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
}}

QComboBox QAbstractItemView {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 4px;
    selection-background-color: {P['accent']};
    selection-color: white;
}}

/* ----------------------------------------------------------
   数字输入框 — SpinBox
   ---------------------------------------------------------- */

QSpinBox, QDoubleSpinBox {{
    background: {P['input_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {P['text_primary']};
    min-height: 32px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {P['accent']};
}}

/* ----------------------------------------------------------
   复选框 / 单选框 — Check / Radio
   ---------------------------------------------------------- */

QCheckBox {{
    spacing: 10px;
    color: {P['text_primary']};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 3px;
    border: 2px solid {P['border']};
    background: {P['card_bg']};
}}

QCheckBox::indicator:checked {{
    background: {P['accent']};
    border-color: {P['accent']};
}}

QCheckBox::indicator:hover {{
    border-color: {P['accent']};
}}

QRadioButton {{
    spacing: 10px;
    color: {P['text_primary']};
}}

QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 2px solid {P['border']};
    background: {P['card_bg']};
}}

QRadioButton::indicator:checked {{
    background: {P['accent']};
    border-color: {P['accent']};
}}

/* ----------------------------------------------------------
   标签页 — Tab Widget
   ---------------------------------------------------------- */

QTabWidget::pane {{
    border: none;
    background: transparent;
    padding-top: 4px;
}}

QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    margin-right: 2px;
    color: {P['text_muted']};
    font-weight: 600;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    color: {P['accent']};
    border-bottom: 2px solid {P['accent']};
}}

QTabBar::tab:hover:!selected {{
    color: {P['text_primary']};
    background: {P['accent_light']};
    border-radius: 4px 4px 0 0;
}}

/* ----------------------------------------------------------
   滚动条 — Scrollbar
   ---------------------------------------------------------- */

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 0 4px 2px;
}}

QScrollBar::handle:vertical {{
    background: {P['border']};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {P['text_muted']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 0 0 0;
}}

QScrollBar::handle:horizontal {{
    background: {P['border']};
    border-radius: 5px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {P['text_muted']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ----------------------------------------------------------
   分割器 — Splitter
   ---------------------------------------------------------- */

QSplitter::handle {{
    background: transparent;
    width: 6px;
}}

QSplitter::handle:hover {{
    background: {P['accent_light']};
}}

QSplitter::handle:pressed {{
    background: {P['accent']};
}}

/* ----------------------------------------------------------
   菜单 — Menu
   ---------------------------------------------------------- */

QMenu {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 8px;
    padding: 6px;
}}

QMenu::item {{
    padding: 8px 28px 8px 16px;
    border-radius: 4px;
    color: {P['text_primary']};
}}

QMenu::item:selected {{
    background: {P['accent']};
    color: white;
}}

QMenu::separator {{
    height: 1px;
    background: {P['border']};
    margin: 4px 8px;
}}

/* ----------------------------------------------------------
   工具提示 — Tooltip
   ---------------------------------------------------------- */

QToolTip {{
    background: {P['text_primary']};
    color: {P['card_bg']};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    border: none;
}}

/* ----------------------------------------------------------
   状态栏 — Status Bar
   ---------------------------------------------------------- */

QStatusBar {{
    background: {P['card_bg']};
    color: {P['text_muted']};
    border-top: 1px solid {P['border']};
    padding: 2px 8px;
    font-size: 12px;
}}

/* ----------------------------------------------------------
   分组框 — GroupBox
   ---------------------------------------------------------- */

QGroupBox {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 8px;
    padding: 16px 12px 12px 12px;
    margin-top: 12px;
    font-weight: 700;
    font-size: 13px;
    color: {P['text_primary']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 1px 10px;
    color: {P['text_primary']};
}}

/* ----------------------------------------------------------
   文本浏览器 — TextBrowser
   ---------------------------------------------------------- */

QTextBrowser {{
    background: {P['card_bg']};
    border: 1px solid {P['border']};
    border-radius: 6px;
    padding: 10px;
    color: {P['text_primary']};
    selection-background-color: {P['accent_light']};
}}

/* ----------------------------------------------------------
   对话框 — Dialog
   ---------------------------------------------------------- */

QDialog {{
    background: {P['bg']};
}}

/* ----------------------------------------------------------
   徽章 — Badges
   ---------------------------------------------------------- */

QLabel#badgeSuccess {{
    background: {P['success']};
    color: white;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#badgeWarning {{
    background: {P['warning']};
    color: white;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#badgeError {{
    background: {P['error']};
    color: white;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#badgeInfo {{
    background: {P['info']};
    color: white;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}

/* ----------------------------------------------------------
   分隔线 — Separator
   ---------------------------------------------------------- */

QFrame#hSeparator {{
    background: {P['border']};
    max-height: 1px;
    border: none;
}}

QFrame#vSeparator {{
    background: {P['border']};
    max-width: 1px;
    border: none;
}}
"""


CSS: str = generate_css(ColorPalette.LIGHT)