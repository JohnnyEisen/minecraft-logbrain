"""
MCA Brain System - PyQt6 主窗口模块

提供主应用窗口类 SiliconeCapsuleApp。
"""

from __future__ import annotations

import csv
import json
import logging
import os
import platform
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.constants import CONFIG_FILE, GPU_ISSUES_FILE
from brain_system import __version__
from mca_core.hardware_analysis import analyze_hardware_log
from mca_core.services.config_service import ConfigService
from mca_core.diagnostic_engine import DiagnosticEngine
from mca_core.services.log_service import LogService
from mca_core.services.system_service import SystemService
from mca_core.archive_utils import (
    collect_logs_from_paths,
    cleanup_temp_dir,
    is_archive_file,
    is_log_file,
)
from mca_core.analysis_engine import (
    load_gpu_rules,
    format_hardware_report,
    scan_mods_directory,
    write_dep_csv,
    read_history_csv,
    build_nx_graph,
)
from mca_core.screen_adapter_pyqt import ScreenAdapter, WindowStateManager
from mca_core.styles_pyqt import CSS
try:
    from mca_core.brain_animation_pyqt import BrainMonitorWidget
except Exception:
    BrainMonitorWidget = None

from mca_core.workers_pyqt import (
    AIInitWorker,
    AnalysisWorker,
    AutoTestWorker,
    HAS_BRAIN,
)
from mca_core.main_window_mixins import MenuMixin, AutoTestMixin, AnalysisMixin

try:
    from mca_core.patch_panel_pyqt import PatchPanel
    HAS_PATCH_PANEL: bool = True
except ImportError:
    HAS_PATCH_PANEL = False
    PatchPanel = None

try:
    from mca_core.dashboard.dashboard_panel_pyqt import DashboardPanelPyQt
    from mca_core.dashboard.controller import DashboardController
    HAS_DASHBOARD_PANEL: bool = True
except ImportError:
    HAS_DASHBOARD_PANEL = False
    DashboardPanelPyQt = None
    DashboardController = None

try:
    from mca_core.dlc_manager_panel_pyqt import DLCManagerPanelPyQt
    HAS_DLC_MANAGER: bool = True
except ImportError:
    HAS_DLC_MANAGER = False
    DLCManagerPanelPyQt = None

if TYPE_CHECKING:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

try:
    import networkx as nx
    HAS_NX: bool = True
except ImportError:
    HAS_NX = False
    nx = None

try:
    from brain_system.core import BrainCore
    HAS_BRAIN_CORE: bool = True
except ImportError:
    HAS_BRAIN_CORE = False
    BrainCore = None

_FigureCanvas: Optional[type] = None
_Figure: Optional[type] = None

SCRIPT_DIR: str = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR: str = os.path.dirname(os.path.dirname(SCRIPT_DIR))
HISTORY_FILE: str = os.path.join(ROOT_DIR, "data", "analysis_history.csv")

MODE_DESCRIPTIONS = [
    ("略微", "保守策略 - 适合低内存环境，减少内存占用但可能增加 CPU 消耗。"),
    ("标准", "推荐配置 - 平衡内存回收频率与分析吞吐量，适合大多数场景。"),
    ("激进", "高性能 - 减少 GC 频率，大幅提升大文件分析速度，但内存占用较高。")
]

_RE_MOD_JAR = re.compile(r"([a-zA-Z0-9_\-]+)-(\d[\w\.\-]+)\.jar")

logger = logging.getLogger(__name__)


class SiliconeCapsuleApp(MenuMixin, AutoTestMixin, AnalysisMixin, QMainWindow):
    """
    MCA 主应用窗口。
    
    提供现代化的拟态风格 UI，用于 Minecraft 崩溃日志分析。
    
    功能特性:
        - 智能屏幕适配
        - 窗口状态记忆
        - 多显示器支持
        - 高 DPI 缩放
    
    继承自:
        MenuMixin: 菜单栏功能
        AutoTestMixin: 自动化测试功能
        AnalysisMixin: 分析功能
        QMainWindow: Qt 主窗口
    
    Attributes:
        log_service: 日志服务
        config_service: 配置服务
        engine: 诊断引擎
        brain: BrainCore AI 引擎
        graph_canvas: 图表画布
        _window_state_manager: 窗口状态管理器
        _use_physical_adaptation: 是否使用物理尺寸适配
    """
    
    tail_line_signal = pyqtSignal(str)

    def _set_brain_monitor_state(self, state: str) -> None:
        """同步状态动画和短标签。"""
        monitor = getattr(self, "brain_monitor", None)
        if monitor is None:
            return
        try:
            monitor.set_ai_state(state)
        except Exception:
            pass

    def _set_status_text(self, text: str) -> None:
        """更新主状态栏文本。"""
        self.status_label.setText(text)

    def __init__(self, use_physical_adaptation: bool = True, debug_mode: bool = False) -> None:
        """
        初始化主应用窗口。
        
        Args:
            use_physical_adaptation: 是否尝试使用物理尺寸适配，默认 True
            debug_mode: 是否启用调试模式，默认 False
        """
        ScreenAdapter.set_debug_mode(debug_mode)
        self._use_physical_adaptation = use_physical_adaptation
        self._window_state_manager = WindowStateManager()
        
        super().__init__()
        self.setAcceptDrops(True)
        self._pending_temp_dirs: list[tuple[str, str]] = []
        self._init_window()
        self._init_backend()
        self.setup_ui()
        self._create_menus()
        self.tail_line_signal.connect(self._append_tail_line)

    def _init_window(self) -> None:
        """
        初始化窗口配置。
        
        执行智能屏幕适配流程:
            1. 尝试恢复上次保存的窗口状态
            2. 如果没有保存状态或状态无效，执行智能适配
            3. 设置窗口大小限制
        """
        self.setWindowTitle("MCA 崩溃分析器")
        self.setStyleSheet(CSS)
        
        self._set_window_icon()
        
        primary_screen = self.screen()
        if primary_screen is None:
            from PyQt6.QtWidgets import QApplication
            primary_screen = QApplication.primaryScreen()
        if primary_screen is None:
            self.resize(1200, 800)
            self.setMinimumSize(ScreenAdapter.MIN_WIDTH, ScreenAdapter.MIN_HEIGHT)
            return
        
        saved_state = self._window_state_manager.load_state()
        
        if saved_state:
            geometry = saved_state.get("geometry")
            screen_name = saved_state.get("screen_name", "")
            was_maximized = saved_state.get("maximized", False)
            
            target_screen = None
            if screen_name:
                target_screen = ScreenAdapter.find_screen_by_name(screen_name)
            
            if target_screen is None:
                target_screen = primary_screen
            
            if geometry and ScreenAdapter.is_window_visible_on_screen(geometry, target_screen):
                self.setGeometry(geometry)
                self.setMinimumSize(ScreenAdapter.MIN_WIDTH, ScreenAdapter.MIN_HEIGHT)
                
                screen_geometry = target_screen.availableGeometry()
                max_width = screen_geometry.width() - 40
                max_height = screen_geometry.height() - 40
                self.setMaximumSize(max_width, max_height)
                
                if was_maximized:
                    self.showMaximized()
                
                ScreenAdapter._log(f"已恢复窗口状态: {geometry.width()}x{geometry.height()}")
                return
            else:
                ScreenAdapter._log("保存的窗口状态无效，执行智能适配")
        
        self._apply_smart_adaptation(primary_screen)

    def _set_window_icon(self) -> None:
        """设置窗口图标。"""
        from PyQt6.QtGui import QIcon
        
        icon_paths = [
            os.path.join(ROOT_DIR, "app_icon.ico"),
            os.path.join(ROOT_DIR, "assets", "app_icon.ico"),
            os.path.join(ROOT_DIR, "resources", "app_icon.ico"),
        ]
        
        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                try:
                    self.setWindowIcon(QIcon(icon_path))
                    return
                except Exception:
                    pass

    def _apply_smart_adaptation(self, screen) -> None:
        """
        应用智能屏幕适配。
        
        优先尝试物理尺寸适配，如果失败则回退到比例适配。
        
        Args:
            screen: 目标屏幕
        """
        width: int
        height: int
        top_margin: int
        
        if self._use_physical_adaptation:
            physical_result = ScreenAdapter.calculate_physical_adaptation(screen)
            if physical_result:
                width, height, top_margin = physical_result
                ScreenAdapter._log("使用物理尺寸适配")
            else:
                width, height = ScreenAdapter.calculate_window_size(screen)
                top_margin = ScreenAdapter.calculate_top_margin(screen)
                ScreenAdapter._log("物理适配不可用，回退到比例适配")
        else:
            width, height = ScreenAdapter.calculate_window_size(screen)
            top_margin = ScreenAdapter.calculate_top_margin(screen)
            ScreenAdapter._log("使用比例适配")
        
        x, y = ScreenAdapter.calculate_window_position(screen, width, height)
        
        self.setGeometry(x, y, width, height)
        
        self.setMinimumSize(ScreenAdapter.MIN_WIDTH, ScreenAdapter.MIN_HEIGHT)
        
        screen_geometry = screen.availableGeometry()
        max_width = screen_geometry.width() - 40
        max_height = screen_geometry.height() - 40
        self.setMaximumSize(max_width, max_height)
        
        ScreenAdapter._log(f"窗口已适配: {width}x{height} @ ({x}, {y})")

    def reset_to_default(self) -> None:
        """
        重置窗口到当前屏幕的默认适配状态。
        
        清除保存的窗口状态，重新执行智能适配。
        """
        self._window_state_manager.clear_state()
        
        current_screen = ScreenAdapter.get_window_screen(self)
        if current_screen is None:
            from PyQt6.QtWidgets import QApplication
            current_screen = QApplication.primaryScreen()
        
        if current_screen:
            self._apply_smart_adaptation(current_screen)
            if self.isMaximized():
                self.showNormal()
        
        ScreenAdapter._log("窗口已重置到默认状态")

    def get_current_screen_info(self) -> dict[str, Any]:
        """
        获取当前屏幕的详细信息。
        
        Returns:
            包含屏幕信息的字典
        """
        current_screen = ScreenAdapter.get_window_screen(self)
        if current_screen is None:
            from PyQt6.QtWidgets import QApplication
            current_screen = QApplication.primaryScreen()
        
        if current_screen:
            return ScreenAdapter.get_screen_info(current_screen)
        
        return {
            "name": "Unknown",
            "resolution": "Unknown",
            "geometry": {},
            "physical_size_mm": {},
            "diagonal_inch": None,
            "dpi": 96,
            "device_pixel_ratio": 1.0,
            "refresh_rate": 60.0,
            "orientation": "Unknown",
            "is_primary": True,
            "calculated_ppi": None,
        }

    def closeEvent(self, event) -> None:
        """
        处理窗口关闭事件。
        
        保存窗口状态到 QSettings。
        
        Args:
            event: 关闭事件对象
        """
        self._window_state_manager.save_state(self)
        ScreenAdapter._log("窗口关闭，状态已保存")
        event.accept()

    # ==================== 拖放支持 ====================

    def _filter_drop_paths(self, urls: list) -> list[str]:
        """从拖放的 URL 列表中筛选有效文件路径。

        Args:
            urls: QUrl 列表

        Returns:
            有效文件路径列表
        """
        from PyQt6.QtCore import QUrl
        paths: list[str] = []
        for url in urls:
            if url.isLocalFile():
                path = url.toLocalFile()
                if os.path.isfile(path) or is_archive_file(path):
                    paths.append(path)
        return paths

    def dragEnterEvent(self, event) -> None:
        """拖入窗口时显示接受指示。"""
        if event.mimeData().hasUrls():
            paths = self._filter_drop_paths(event.mimeData().urls())
            if paths:
                event.acceptProposedAction()
                self._set_drag_overlay_visible(True)
                return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        """拖动过程中保持接受状态。"""
        if event.mimeData().hasUrls():
            paths = self._filter_drop_paths(event.mimeData().urls())
            if paths:
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        """拖离窗口时隐藏提示。"""
        self._set_drag_overlay_visible(False)
        event.accept()

    def dropEvent(self, event) -> None:
        """释放拖放文件时加载日志。"""
        self._set_drag_overlay_visible(False)
        if event.mimeData().hasUrls():
            paths = self._filter_drop_paths(event.mimeData().urls())
            if paths:
                event.acceptProposedAction()
                self.load_from_paths(paths)
                return
        event.ignore()

    def resizeEvent(self, event) -> None:
        """窗口大小改变时更新拖放覆盖层位置。"""
        super().resizeEvent(event)
        if hasattr(self, "_drag_overlay") and self._drag_overlay.isVisible():
            self._drag_overlay.setGeometry(self.rect())

    def _set_drag_overlay_visible(self, visible: bool) -> None:
        """显示/隐藏拖放提示覆盖层。

        Args:
            visible: 是否显示
        """
        if not hasattr(self, "_drag_overlay"):
            self._drag_overlay = QLabel(self)
            self._drag_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._drag_overlay.setStyleSheet("""
                QLabel {
                    background: rgba(44, 163, 237, 0.85);
                    color: white;
                    font-size: 24px;
                    font-weight: bold;
                    border: 3px dashed rgba(255, 255, 255, 0.8);
                    border-radius: 12px;
                }
            """)
            self._drag_overlay.setText("松开以加载日志文件")
            self._drag_overlay.setVisible(False)

        if visible:
            self._drag_overlay.setGeometry(self.rect())
            self._drag_overlay.raise_()
        self._drag_overlay.setVisible(visible)

    # ==================== 后端初始化 ====================

    def _init_backend(self) -> None:
        """初始化后端服务。"""
        self.log_service = LogService()
        self.config_service = ConfigService(CONFIG_FILE)
        data_dir = os.path.join(ROOT_DIR, "data")
        os.makedirs(data_dir, exist_ok=True)
        self.engine = DiagnosticEngine(data_dir=data_dir)
        self.file_path = ""
        self.current_dep_pairs: set[tuple[str, str]] = set()
        self.current_mods: dict[str, set] = {}
        self.current_cause_counts: dict[str, int] = {}
        self._tail_running = False
        self._tail_stop_event = threading.Event()
        self.graph_layout_name = "spring"
        self.filter_isolated_nodes = True
        self.gl_snippets: list[str] = []
        self.hardware_issues: list[str] = []
        self.auto_test_worker: Optional[AutoTestWorker] = None
        self.ai_init_worker: Optional[AIInitWorker] = None
        self.brain: Any = None
        self.graph_canvas: Any = None
        self._graph_placeholder: Optional[QLabel] = None
        self._brain_config_path: Optional[str] = None
        self.dashboard_controller: Any = None
        
        brain_config = os.path.join(ROOT_DIR, "config", "brain_config.json")
        if not os.path.exists(brain_config):
            brain_config = None
        self._brain_config_path = brain_config

    def _ensure_graph_canvas(self) -> bool:
        """确保图表画布已初始化。"""
        if self.graph_canvas is not None:
            return True

        global _FigureCanvas, _Figure
        if _FigureCanvas is None or _Figure is None:
            try:
                from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as _FigureCanvas
                from matplotlib.figure import Figure as _Figure
                _FigureCanvas = _FigureCanvas
                _Figure = _Figure
            except Exception as e:
                QMessageBox.warning(self, "图表初始化失败", f"无法加载 Matplotlib 图形后端: {e}")
                return False

        try:
            self.graph_canvas = _FigureCanvas(_Figure(figsize=(5, 4), dpi=100))
            if self._graph_placeholder is not None:
                self.tab_graphs_layout.removeWidget(self._graph_placeholder)
                self._graph_placeholder.deleteLater()
                self._graph_placeholder = None
            self.tab_graphs_layout.addWidget(self.graph_canvas)
            return True
        except Exception as e:
            QMessageBox.warning(self, "图表初始化失败", f"创建图表控件失败: {e}")
            self.graph_canvas = None
            return False

    def _create_menus(self) -> None:
        """创建菜单栏。"""
        menubar = self.menuBar()
        if menubar is None:
            return
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: transparent;
                padding: 4px;
                font-size: 14px;
            }
            QMenuBar::item {
                padding: 4px 10px;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background-color: #e2e8f0;
            }
        """)

        self._create_file_menu(menubar)
        self._create_tools_menu(menubar)
        self._create_view_menu(menubar)
        self._create_help_menu(menubar)

    def _create_file_menu(self, menubar: Optional[QMenuBar]) -> None:
        """创建文件菜单。"""
        if menubar is None:
            return
        file_menu = menubar.addMenu("文件(F)")
        
        action_open = QAction("打开日志文件...", self)
        action_open.setShortcut("Ctrl+O")
        action_open.triggered.connect(self.on_load_clicked)
        file_menu.addAction(action_open)

        action_import_mods = QAction("导入 Mods 列表...", self)
        action_import_mods.triggered.connect(self.import_mods)
        file_menu.addAction(action_import_mods)
        
        action_clear = QAction("清除日志", self)
        action_clear.triggered.connect(self.clear_content)
        file_menu.addAction(action_clear)
        
        file_menu.addSeparator()
        
        action_exit = QAction("退出", self)
        action_exit.setShortcut("Ctrl+Q")
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

    def _create_tools_menu(self, menubar: Optional[QMenuBar]) -> None:
        """创建工具菜单。"""
        if menubar is None:
            return
        tools_menu = menubar.addMenu("工具(T)")
        
        action_export_report = QAction("导出分析报告", self)
        action_export_report.triggered.connect(self.export_report)
        tools_menu.addAction(action_export_report)

        action_start_ai = QAction("启动分析引擎", self)
        action_start_ai.triggered.connect(self.start_ai_init_if_needed)
        tools_menu.addAction(action_start_ai)

        action_export_deps = QAction("导出依赖关系(CSV)", self)
        action_export_deps.triggered.connect(self.export_dependencies)
        tools_menu.addAction(action_export_deps)

        action_save_graph = QAction("保存依赖图(PNG)", self)
        action_save_graph.triggered.connect(self.save_dependency_graph)
        tools_menu.addAction(action_save_graph)

        tools_menu.addSeparator()
        action_toggle_tail = QAction("开启/停止日志实时跟踪(Tail)", self)
        action_toggle_tail.triggered.connect(self.toggle_tail)
        tools_menu.addAction(action_toggle_tail)

        tools_menu.addSeparator()
        action_launch_generator = QAction("启动场景生成器(CLI)", self)
        action_launch_generator.triggered.connect(self.launch_adversarial_gen)
        tools_menu.addAction(action_launch_generator)

        action_launch_gpu_setup = QAction("GPU 环境配置向导", self)
        action_launch_gpu_setup.triggered.connect(self.launch_gpu_setup)
        tools_menu.addAction(action_launch_gpu_setup)
        
        action_view_history = QAction("查看分析历史", self)
        action_view_history.triggered.connect(self.view_history)
        tools_menu.addAction(action_view_history)

    def _create_view_menu(self, menubar: Optional[QMenuBar]) -> None:
        """创建视图菜单。"""
        if menubar is None:
            return
        view_menu = menubar.addMenu("视图(V)")

        action_refresh_hardware = QAction("刷新硬件分析", self)
        action_refresh_hardware.triggered.connect(self.refresh_hardware_analysis)
        view_menu.addAction(action_refresh_hardware)

        action_copy_gl = QAction("复制 GL 片段", self)
        action_copy_gl.triggered.connect(self.copy_gl_snippets)
        view_menu.addAction(action_copy_gl)

        action_copy_prompt = QAction("复制诊断提示词 (Tier 3)", self)
        action_copy_prompt.triggered.connect(self.copy_ai_prompt)
        view_menu.addAction(action_copy_prompt)

        view_menu.addSeparator()
        layout_menu = view_menu.addMenu("依赖图布局")
        self.layout_actions: dict[str, QAction] = {}
        layout_group = QActionGroup(self)
        layout_group.setExclusive(True)
        for layout_key, label in [
            ("spring", "Spring"),
            ("circular", "Circular"),
            ("shell", "Shell"),
            ("spectral", "Spectral"),
            ("random", "Random"),
        ]:
            act = QAction(label, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, k=layout_key: self.set_graph_layout(k))
            layout_group.addAction(act)
            layout_menu.addAction(act)
            self.layout_actions[layout_key] = act
        self.layout_actions["spring"].setChecked(True)

        action_filter_iso = QAction("过滤孤立节点", self)
        action_filter_iso.setCheckable(True)
        action_filter_iso.setChecked(True)
        action_filter_iso.triggered.connect(self.set_filter_isolated)
        view_menu.addAction(action_filter_iso)
        self.action_filter_isolated = action_filter_iso

    def _create_help_menu(self, menubar: Optional[QMenuBar]) -> None:
        """创建帮助菜单。"""
        if menubar is None:
            return
        help_menu = menubar.addMenu("帮助(H)")
        action_about = QAction("关于 MCA", self)
        action_about.triggered.connect(self.show_about)
        help_menu.addAction(action_about)

    def clear_content(self) -> None:
        """清除所有内容。"""
        self.log_text_edit.clear()
        self._set_status_text("状态: 就绪")
        self._set_brain_monitor_state("idle")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("开始分析")
        self.file_path = ""
        self.current_dep_pairs = set()
        self.current_mods = {}
        self.current_cause_counts = {}
        self.gl_snippets = []
        self.hardware_issues = []
        if self._tail_running:
            self._tail_stop_event.set()
            self._tail_running = False
        if self.auto_test_worker and self.auto_test_worker.isRunning():
            self.auto_test_worker.cancel()
        self.result_text_edit.clear()
        self.mod_list_widget.clear()
        if hasattr(self, "hardware_text_edit"):
            self.hardware_text_edit.clear()
        
        while self.tab_graphs_layout.count():
            item = self.tab_graphs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.progress.setValue(0)
        self.progress.hide()

    def export_report(self) -> None:
        """导出分析报告。"""
        report_text = self.result_text_edit.toPlainText()
        if not report_text:
            QMessageBox.warning(self, "无内容", "当前没有分析结果可供导出。")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存分析报告",
            os.path.join(os.path.expanduser("~"), "MCA_Report.txt"),
            "Text Files (*.txt);;Markdown Files (*.md);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(report_text)
                QMessageBox.information(self, "导出成功", f"报告已成功导出至：\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"无法写入文件：{str(e)}")

    def export_dependencies(self) -> None:
        """导出依赖关系。"""
        if not self.current_dep_pairs:
            QMessageBox.information(self, "提示", "没有依赖数据可导出。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存依赖关系",
            os.path.join(os.path.expanduser("~"), "mod_dependencies.csv"),
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            write_dep_csv(file_path, self.current_dep_pairs, self.current_mods)
            QMessageBox.information(self, "导出成功", f"依赖关系已导出至:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"无法导出依赖关系: {e}")

    def save_dependency_graph(self) -> None:
        """保存依赖图。"""
        if not self._ensure_graph_canvas():
            return

        if not self.graph_canvas.figure.axes:
            QMessageBox.information(self, "提示", "当前没有可保存的图表。")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存依赖图",
            os.path.join(os.path.expanduser("~"), "dependency_graph.png"),
            "PNG Files (*.png);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self.graph_canvas.figure.savefig(file_path, dpi=180, bbox_inches="tight")
            QMessageBox.information(self, "保存成功", f"图表已保存至:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存图表失败: {e}")

    def toggle_tail(self) -> None:
        """切换日志跟踪状态。"""
        if self._tail_running:
            self._tail_running = False
            self._tail_stop_event.set()
            self._set_status_text("状态: 日志跟踪已停止")
            return

        if not self.file_path or not os.path.exists(self.file_path):
            QMessageBox.information(self, "提示", "请先加载一个有效的本地日志文件。")
            return

        self._tail_running = True
        self._tail_stop_event.clear()
        self._set_status_text("状态: 正在跟踪日志变化...")
        threading.Thread(target=self._tail_worker, daemon=True).start()

    def _tail_worker(self) -> None:
        """日志跟踪工作线程。"""
        try:
            with open(self.file_path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(0, 2)
                while not self._tail_stop_event.is_set():
                    line = f.readline()
                    if line:
                        self.tail_line_signal.emit(line)
                    else:
                        time.sleep(0.4)
        except Exception as e:
            self.tail_line_signal.emit(f"\n[tail错误] {e}\n")
        finally:
            self._tail_running = False

    def _append_tail_line(self, line: str) -> None:
        """追加日志行。"""
        self.log_text_edit.moveCursor(self.log_text_edit.textCursor().MoveOperation.End)
        self.log_text_edit.insertPlainText(line)
        self.log_text_edit.ensureCursorVisible()
        self.log_service.append_line(line)

    def launch_adversarial_gen(self) -> None:
        """启动场景生成器。"""
        script_path = os.path.join(ROOT_DIR, "scripts", "dev", "generate_mc_log.py")
        if not os.path.exists(script_path):
            QMessageBox.warning(self, "启动失败", f"未找到脚本: {script_path}")
            return

        try:
            import subprocess
            if os.name == "nt":
                subprocess.Popen([
                    "cmd", "/c", "start", "cmd", "/k", f'"{sys.executable}" "{script_path}" --help'
                ], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            else:
                subprocess.Popen([sys.executable, script_path, "--help"])
            QMessageBox.information(self, "已启动", "场景生成器已在新终端中启动。")
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))

    def launch_gpu_setup(self) -> None:
        """启动 GPU 配置向导。"""
        script_path = os.path.join(ROOT_DIR, "tools", "gpu_setup.py")
        if not os.path.exists(script_path):
            QMessageBox.warning(self, "启动失败", f"未找到脚本: {script_path}")
            return

        try:
            import subprocess
            if os.name == "nt":
                subprocess.Popen([
                    "cmd", "/c", "start", "cmd", "/k", f'"{sys.executable}" "{script_path}"'
                ], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            else:
                subprocess.Popen([sys.executable, script_path])
            QMessageBox.information(self, "已启动", "GPU 配置向导已在新终端中启动。")
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))

    def set_graph_layout(self, layout_name: str) -> None:
        """设置图表布局。"""
        self.graph_layout_name = layout_name
        if self.current_dep_pairs or self.current_cause_counts:
            self.draw_graphs(self.current_dep_pairs, self.current_cause_counts)

    def set_filter_isolated(self, checked: bool) -> None:
        """设置是否过滤孤立节点。"""
        self.filter_isolated_nodes = bool(checked)
        if self.current_dep_pairs or self.current_cause_counts:
            self.draw_graphs(self.current_dep_pairs, self.current_cause_counts)

    def refresh_hardware_analysis(self) -> None:
        """刷新硬件分析。"""
        text = self.log_text_edit.toPlainText() or ""
        system_info: dict[str, Any] = {}
        try:
            system_info = SystemService().get_system_info()
        except Exception:
            system_info = {}

        gpu_rules = load_gpu_rules()

        result = analyze_hardware_log(
            text,
            current_mods=self.current_mods,
            system_info=system_info,
            gpu_rules=gpu_rules,
            max_snippets=24,
        )

        self.hardware_issues = result["suggestions"]
        self.gl_snippets = result["snippets"]

        self.hardware_text_edit.setPlainText(format_hardware_report(result, system_info))
        self.tabs.setCurrentIndex(3)

    def copy_gl_snippets(self) -> None:
        """复制 GL 片段。"""
        if not self.gl_snippets:
            QMessageBox.information(self, "提示", "当前没有可复制的 GL 片段。")
            return

        text = "\n---\n".join(self.gl_snippets)
        from PyQt6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        cb.setText(text)
        QMessageBox.information(self, "复制成功", "GL 片段已复制到剪贴板。")

    def copy_ai_prompt(self) -> None:
        """生成并复制 AI 诊断提示词。"""
        log_content = self.log_text_edit.toPlainText()
        if not log_content.strip():
            QMessageBox.warning(self, "无内容", "没有加载日志内容。")
            return
            
        try:
            from mca_core.prompt_generator import PromptGenerator
            prompt = PromptGenerator.generate_prompt(log_content)
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(prompt)
            QMessageBox.information(self, "复制成功", "已成功生成并复制提示词！现在可粘贴至 ChatGPT/DeepSeek 等外部 AI 获得诊断。")
        except Exception as e:
            logger.error(f"Failed to generate prompt: {e}")
            QMessageBox.warning(self, "生成失败", f"无法生成提示词: {e}")

    def start_auto_test(self) -> None:
        """开始自动化测试。"""
        output_dir = self.auto_test_output_edit.text().strip() or os.path.join(ROOT_DIR, "tmp", "autotests")
        os.makedirs(output_dir, exist_ok=True)

        selected = self.auto_test_scenarios.selectedItems()
        scenarios = [item.text().split("-")[0].strip() for item in selected]
        if not scenarios:
            scenarios = ["normal"]

        count = int(self.auto_test_count_spin.value())
        cleanup = bool(self.auto_test_cleanup_check.isChecked())
        run_analysis = bool(self.auto_test_run_analysis_check.isChecked())

        self.auto_test_log_edit.clear()
        self.auto_test_progress.setValue(0)
        self.auto_test_progress.setMaximum(max(count, 1))
        self.btn_auto_test_start.setEnabled(False)
        self.btn_auto_test_stop.setEnabled(True)
        self.auto_test_stats_label.setText("统计: 运行中...")
        self.tabs.setCurrentIndex(4)

        worker = AutoTestWorker(
            output_dir, 
            scenarios, 
            count, 
            cleanup,
            engine=self.engine,
            run_analysis=run_analysis
        )
        worker.signals.log.connect(self.auto_test_log_edit.append)
        worker.signals.progress.connect(lambda cur, total: self.auto_test_progress.setValue(cur))
        worker.signals.stats.connect(self.on_auto_test_stats)
        worker.signals.error.connect(self.on_auto_test_error)
        worker.signals.finished.connect(self.on_auto_test_finished)
        self.auto_test_worker = worker
        worker.start()

    def stop_auto_test(self) -> None:
        """停止自动化测试。"""
        if self.auto_test_worker:
            self.auto_test_worker.cancel()
            self.auto_test_log_edit.append("用户请求停止自动化测试...")

    def on_auto_test_stats(self, gen_time: str, samples: str, cleanup_msg: str) -> None:
        """处理自动化测试统计。"""
        self.auto_test_stats_label.setText(f"统计: 生成耗时 {gen_time}, 样本数 {samples}, {cleanup_msg}")

    def on_auto_test_error(self, msg: str) -> None:
        """处理自动化测试错误。"""
        self.auto_test_log_edit.append(f"[错误] {msg}")

    def on_auto_test_finished(self) -> None:
        """处理自动化测试完成。"""
        self.btn_auto_test_start.setEnabled(True)
        self.btn_auto_test_stop.setEnabled(False)
        self.auto_test_log_edit.append("自动化测试结束。")
        self.auto_test_worker = None

    def start_ai_init_if_needed(self) -> None:
        """启动 AI 引擎初始化。"""
        if self.brain is not None:
            QMessageBox.information(self, "提示", "语义分析模块已启用。")
            return
        if not HAS_BRAIN or not HAS_BRAIN_CORE:
            QMessageBox.warning(self, "不可用", "当前环境未安装分析模块，无法启用语义分析。")
            return

        self.btn_start_ai.setEnabled(False)
        self.btn_start_ai.setText("启动中...")
        self._set_brain_monitor_state("loading")
        self._set_status_text("状态: 正在加载语义分析模块...")

        worker = AIInitWorker(self._brain_config_path)
        worker.signals.done.connect(self.on_ai_init_done)
        worker.signals.progress.connect(self._on_ai_init_progress)
        self.ai_init_worker = worker

        self._ai_init_timeout_timer = QTimer(self)
        self._ai_init_timeout_timer.setSingleShot(True)
        self._ai_init_timeout_timer.timeout.connect(self._on_ai_init_long_wait)
        self._ai_init_timeout_timer.start(30000)
        
        worker.start()

    def _on_ai_init_progress(self, msg: str) -> None:
        """处理 AI 初始化进度更新。"""
        self._set_status_text(f"状态: {msg}")

    def _on_ai_init_long_wait(self) -> None:
        """处理 AI 初始化长时间等待。"""
        if self.ai_init_worker and self.ai_init_worker.isRunning():
            self._set_status_text("状态: 仍在下载语义模型 (all-MiniLM-L6-v2, ~90MB) - 请稍候...")
            self._set_brain_monitor_state("warning")
            self.btn_start_ai.setText("下载中...")

    def on_ai_init_done(self, ok: bool, payload: Any) -> None:
        """处理 AI 引擎初始化完成。"""
        if hasattr(self, '_ai_init_timeout_timer') and self._ai_init_timeout_timer:
            self._ai_init_timeout_timer.stop()
            self._ai_init_timeout_timer = None
        
        self.btn_start_ai.setEnabled(True)
        if ok:
            self.brain = payload
            self.btn_start_ai.setText("已启用")
            self.btn_start_ai.setEnabled(False)
            self._set_brain_monitor_state("active")
            self._set_status_text("状态: 语义分析模块已就绪")
            if hasattr(self, "dlc_manager_panel") and self.dlc_manager_panel is not None:
                self.dlc_manager_panel.set_brain(self.brain)
            QMessageBox.information(self, "成功", "语义分析模块已启用。")
        else:
            self.btn_start_ai.setText("启用语义分析")
            self._set_brain_monitor_state("error")
            reason = str(payload) if payload else "未知错误"
            if "超时" in reason:
                self._set_status_text(f"状态: 语义分析模块初始化超时 ({reason})")
            else:
                self._set_status_text(f"状态: 语义分析模块启用失败: {reason}")
            QMessageBox.warning(self, "启动失败", f"无法启用语义分析模块: {reason}")

    def view_history(self) -> None:
        """查看分析历史。"""
        history_file = HISTORY_FILE
        if not os.path.exists(history_file):
            QMessageBox.information(self, "历史记录", "暂无分析历史记录。")
            return
            
        dialog = QDialog(self)
        dialog.setWindowTitle("分析历史记录")
        dialog.resize(800, 400)
        dialog.setStyleSheet(self.styleSheet())
        
        layout = QVBoxLayout(dialog)
        
        tree = QTreeWidget()
        tree.setHeaderLabels(["时间", "摘要", "文件路径"])
        tree.setColumnWidth(0, 150)
        tree.setColumnWidth(1, 400)
        tree.setColumnWidth(2, 200)
        
        try:
            rows = read_history_csv(history_file)
            for row in reversed(rows):
                if len(row) >= 3:
                    item = QTreeWidgetItem(row[:3])
                    tree.addTopLevelItem(item)
        except Exception as e:
            QMessageBox.warning(self, "读取失败", f"无法读取历史记录: {e}")
            return
            
        tree.itemDoubleClicked.connect(lambda item, col: self.load_log_from_history(item.text(2), dialog))
        layout.addWidget(tree)
        dialog.exec()

    def load_log_from_history(self, filepath: str, dialog: QDialog) -> None:
        """从历史记录加载日志。"""
        if not os.path.exists(filepath):
            QMessageBox.warning(dialog, "文件不存在", f"无法找到日志文件: {filepath}")
            return
        
        self.load_log_file(filepath)
        dialog.accept()

    def show_about(self) -> None:
        """显示关于对话框。"""
        QMessageBox.about(
            self,
            "关于 MCA 崩溃分析器",
            f"<h2>Minecraft 崩溃日志分析器</h2>"
            f"<p><b>版本:</b> {__version__} (PyQt6)</p>"
            f"<p>用于分析崩溃日志并提供排查建议。</p>"
            f"<p>界面框架: PyQt6</p>"
        )

    def setup_ui(self) -> None:
        """设置 UI。"""
        self.central_widget = QWidget(self)
        self.central_widget.setObjectName("mainContainer")
        self.setCentralWidget(self.central_widget)
        
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(24, 24, 24, 24)
        self.main_layout.setSpacing(16)
        
        self._setup_header()
        self._setup_toolbar()
        self._setup_splitter()

    def _setup_header(self) -> None:
        """设置标题。"""
        self.header_label = QLabel("Minecraft 崩溃日志分析系统 (PyQt6)")
        self.header_label.setObjectName("h1")
        self.main_layout.addWidget(self.header_label, alignment=Qt.AlignmentFlag.AlignCenter)

    def _setup_toolbar(self) -> None:
        """设置工具栏。"""
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setSpacing(8)
        
        self.btn_load = QPushButton("加载日志")
        self.btn_load.setObjectName("toolbarBtn")
        self.btn_load.clicked.connect(self.on_load_clicked)
        
        self.btn_analyze = QPushButton("开始分析")
        self.btn_analyze.setObjectName("accentButton")
        self.btn_analyze.clicked.connect(self.on_analyze_clicked)
        self.btn_analyze.setEnabled(False)
        
        self.btn_settings = QPushButton("系统设置")
        self.btn_settings.setObjectName("toolbarBtn")
        self.btn_settings.clicked.connect(self.on_settings_clicked)

        self.btn_patch = QPushButton("补丁管理")
        self.btn_patch.setObjectName("toolbarBtn")
        self.btn_patch.clicked.connect(self._on_patch_clicked)
        if not HAS_PATCH_PANEL:
            self.btn_patch.setEnabled(False)
            self.btn_patch.setToolTip("补丁管理模块不可用 (mca_core.patch_panel_pyqt 导入失败)")

        self.btn_dashboard = QPushButton("仪表盘")
        self.btn_dashboard.setObjectName("toolbarBtn")
        self.btn_dashboard.clicked.connect(self._on_dashboard_clicked)
        if not HAS_DASHBOARD_PANEL:
            self.btn_dashboard.setEnabled(False)
            self.btn_dashboard.setToolTip("仪表盘模块不可用 (mca_core.dashboard.dashboard_panel_pyqt 导入失败)")

        self.btn_dlc_manager = QPushButton("DLC 管理")
        self.btn_dlc_manager.setObjectName("toolbarBtn")
        self.btn_dlc_manager.clicked.connect(self._on_dlc_manager_clicked)
        if not HAS_DLC_MANAGER:
            self.btn_dlc_manager.setEnabled(False)
            self.btn_dlc_manager.setToolTip("DLC 管理模块不可用 (mca_core.dlc_manager_panel_pyqt 导入失败)")

        self.btn_start_ai = QPushButton("启用语义分析")
        self.btn_start_ai.setObjectName("toolbarBtn")
        self.btn_start_ai.clicked.connect(self.start_ai_init_if_needed)
        
        exact_version = platform.python_version()
        self.status_label = QLabel("")
        self.status_label.setObjectName("caption")

        self.brain_monitor = None
        if BrainMonitorWidget is not None:
            try:
                self.brain_monitor = BrainMonitorWidget(self)
            except Exception:
                self.brain_monitor = None
        
        self.toolbar_layout.addWidget(self.btn_load)
        self.toolbar_layout.addWidget(self.btn_analyze)
        self.toolbar_layout.addWidget(self.btn_patch)
        self.toolbar_layout.addWidget(self.btn_dashboard)
        self.toolbar_layout.addWidget(self.btn_dlc_manager)
        self.toolbar_layout.addWidget(self.btn_start_ai)
        self.toolbar_layout.addWidget(self.btn_settings)
        self.toolbar_layout.addWidget(self.status_label)
        if self.brain_monitor is not None:
            self.toolbar_layout.addWidget(self.brain_monitor)
        self.toolbar_layout.addStretch()
        self.main_layout.addLayout(self.toolbar_layout)
        self._set_status_text(f"状态: 等待加载日志... | 核心驱动: Python {exact_version}")

    def _setup_splitter(self) -> None:
        """设置分割器。"""
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self._setup_log_card()
        self._setup_right_card()
        
        self.splitter.addWidget(self.log_card)
        self.splitter.addWidget(self.right_card)
        self.splitter.setSizes([500, 700])
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 7)
        self.splitter.setHandleWidth(6)

        self.main_layout.addWidget(self.splitter, stretch=1)

    def _setup_log_card(self) -> None:
        """设置日志卡片。"""
        self.log_card = QFrame()
        self.log_card.setObjectName("siliconeCard")
        self.log_layout = QVBoxLayout(self.log_card)
        
        log_title = QLabel("崩溃日志原文")
        log_title.setObjectName("sectionHeader")
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setPlaceholderText("点击上方「加载日志」按钮或拖拽日志文件 / 压缩包到此窗口...")
        self.log_text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px; border: none; background: transparent;")
        
        self.log_layout.addWidget(log_title)
        self.log_layout.addWidget(self.log_text_edit)

    def _setup_right_card(self) -> None:
        """设置右侧卡片。"""
        self.right_card = QFrame()
        self.right_card.setObjectName("siliconeCard")
        self.right_layout = QVBoxLayout(self.right_card)
        
        self._setup_tabs()
        
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.hide()
        
        self.right_layout.addWidget(self.tabs)
        self.right_layout.addWidget(self.progress)

    def _setup_tabs(self) -> None:
        """设置标签页。"""
        self.tabs = QTabWidget()
        self.tabs.setCursor(Qt.CursorShape.ArrowCursor)
        
        self._setup_results_tab()
        self._setup_mods_tab()
        self._setup_graphs_tab()
        self._setup_hardware_tab()
        self._setup_auto_test_tab()
        self._setup_patch_tab()
        self._setup_dashboard_tab()
        self._setup_dlc_manager_tab()

        self.tabs.addTab(self.tab_results, "诊断报告")
        self.tabs.addTab(self.tab_mods, "环境与模组")
        self.tabs.addTab(self.tab_graphs, "依赖图表")
        self.tabs.addTab(self.tab_hardware, "硬件分析")
        self.tabs.addTab(self.tab_auto_test, "自动化测试")
        self.tabs.addTab(self.tab_patch, "补丁管理")
        self.tabs.addTab(self.tab_dashboard, "仪表盘")
        self.tabs.addTab(self.tab_dlc_manager, "DLC 管理")

    def _setup_results_tab(self) -> None:
        """设置结果标签页。"""
        self.tab_results = QWidget()
        self.tab_results_layout = QVBoxLayout(self.tab_results)
        self.result_text_edit = QTextEdit()
        self.result_text_edit.setReadOnly(True)
        self.result_text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 13px; border: none; background: transparent;")
        self.tab_results_layout.addWidget(self.result_text_edit)

    def _setup_mods_tab(self) -> None:
        """设置模组标签页。"""
        self.tab_mods = QWidget()
        self.tab_mods_layout = QVBoxLayout(self.tab_mods)
        self.mod_list_widget = QListWidget()
        self.mod_list_widget.setStyleSheet("border: none; background: transparent;")
        self.tab_mods_layout.addWidget(self.mod_list_widget)

    def _setup_graphs_tab(self) -> None:
        """设置图表标签页。"""
        self.tab_graphs = QWidget()
        self.tab_graphs_layout = QVBoxLayout(self.tab_graphs)
        self._graph_placeholder = QLabel("图表模块将在首次绘制时初始化")
        self._graph_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._graph_placeholder.setObjectName("caption")
        self.tab_graphs_layout.addWidget(self._graph_placeholder)

    def _setup_hardware_tab(self) -> None:
        """设置硬件标签页。"""
        self.tab_hardware = QWidget()
        self.tab_hardware_layout = QVBoxLayout(self.tab_hardware)
        self.hardware_text_edit = QTextEdit()
        self.hardware_text_edit.setReadOnly(True)
        self.hardware_text_edit.setPlaceholderText("分析后显示硬件/GL 相关建议...")
        self.hardware_text_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 12px; border: none; background: transparent;")
        self.tab_hardware_layout.addWidget(self.hardware_text_edit)

    def _setup_auto_test_tab(self) -> None:
        """设置自动测试标签页。"""
        self.tab_auto_test = QWidget()
        self.tab_auto_test_layout = QVBoxLayout(self.tab_auto_test)
        self.tab_auto_test_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)

        config_panel = QFrame()
        config_panel.setObjectName("siliconeCard")
        config_layout = QVBoxLayout(config_panel)
        config_layout.setContentsMargins(8, 8, 8, 8)
        config_layout.setSpacing(6)

        config_heading = QLabel("测试配置")
        config_heading.setObjectName("sectionHeader")
        config_layout.addWidget(config_heading)

        auto_form = QFormLayout()
        auto_form.setSpacing(4)
        self.auto_test_output_edit = QLineEdit(os.path.join(ROOT_DIR, "tmp", "autotests"))
        self.auto_test_output_edit.setPlaceholderText("自动生成日志输出目录")
        auto_form.addRow(QLabel("输出目录:"), self.auto_test_output_edit)

        self.auto_test_count_spin = QSpinBox()
        self.auto_test_count_spin.setRange(1, 5000)
        self.auto_test_count_spin.setValue(10)
        auto_form.addRow(QLabel("生成数量:"), self.auto_test_count_spin)

        self.auto_test_run_analysis_check = QCheckBox("生成后自动执行分析")
        self.auto_test_run_analysis_check.setChecked(True)
        auto_form.addRow(QLabel("分析模式:"), self.auto_test_run_analysis_check)

        self.auto_test_cleanup_check = QCheckBox("完成后自动清理生成文件")
        self.auto_test_cleanup_check.setChecked(True)
        auto_form.addRow(QLabel("清理选项:"), self.auto_test_cleanup_check)
        config_layout.addLayout(auto_form)

        scenario_label = QLabel("测试场景 (可多选):")
        scenario_label.setObjectName("body-sm")
        config_layout.addWidget(scenario_label)

        self.auto_test_scenarios = QListWidget()
        self.auto_test_scenarios.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.auto_test_scenarios.setMaximumHeight(140)
        try:
            from scripts.dev.generate_mc_log import SCENARIOS
        except ImportError:
            SCENARIOS = {
                "normal": "正常日志",
                "oom": "内存溢出",
                "missing_dependency": "缺失前置",
                "gl_error": "OpenGL 错误",
                "mixin_conflict": "Mixin 冲突",
                "version_conflict": "版本冲突",
                "compound": "复合错误",
                "adversarial": "对抗样本",
            }
        for key, cfg in SCENARIOS.items():
            desc = cfg.get("description", key) if isinstance(cfg, dict) else str(cfg)
            self.auto_test_scenarios.addItem(f"{key} - {desc}")
        self.auto_test_scenarios.addItem("custom - 自定义日志 (粘贴到下框)")
        for i in range(self.auto_test_scenarios.count() - 1):
            self.auto_test_scenarios.item(i).setSelected(True)
        config_layout.addWidget(self.auto_test_scenarios)

        auto_btns = QHBoxLayout()
        auto_btns.setSpacing(8)
        self.btn_auto_test_start = QPushButton("开始自动化测试")
        self.btn_auto_test_start.setObjectName("accentButton")
        self.btn_auto_test_start.clicked.connect(self.start_auto_test)
        self.btn_auto_test_stop = QPushButton("停止")
        self.btn_auto_test_stop.setObjectName("dangerBtn")
        self.btn_auto_test_stop.clicked.connect(self.stop_auto_test)
        self.btn_auto_test_stop.setEnabled(False)
        auto_btns.addWidget(self.btn_auto_test_start)
        auto_btns.addWidget(self.btn_auto_test_stop)
        auto_btns.addStretch()
        config_layout.addLayout(auto_btns)

        self.auto_test_progress = QProgressBar()
        self.auto_test_progress.setValue(0)
        config_layout.addWidget(self.auto_test_progress)

        self.auto_test_stats_label = QLabel("统计: 生成耗时 -, 样本数 -, 清理状态 -")
        self.auto_test_stats_label.setObjectName("caption")
        config_layout.addWidget(self.auto_test_stats_label)

        log_panel = QFrame()
        log_panel.setObjectName("siliconeCard")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(8, 8, 8, 8)

        log_heading = QLabel("测试日志")
        log_heading.setObjectName("sectionHeader")
        log_layout.addWidget(log_heading)

        self.auto_test_log_edit = QTextEdit()
        self.auto_test_log_edit.setReadOnly(True)
        self.auto_test_log_edit.setPlaceholderText("自动化测试日志输出...")
        self.auto_test_log_edit.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; border: none; background: transparent;"
        )
        log_layout.addWidget(self.auto_test_log_edit)

        splitter.addWidget(config_panel)
        splitter.addWidget(log_panel)
        splitter.setSizes([320, 280])

        self.tab_auto_test_layout.addWidget(splitter)

    def _setup_patch_tab(self) -> None:
        """设置补丁管理标签页。"""
        self.tab_patch = QWidget()
        self.tab_patch_layout = QVBoxLayout(self.tab_patch)
        self.tab_patch_layout.setContentsMargins(0, 0, 0, 0)

        if HAS_PATCH_PANEL:
            if PatchPanel is None:
                raise RuntimeError("补丁管理面板模块导入失败")
            self.patch_panel = PatchPanel(parent=self)
            self.tab_patch_layout.addWidget(self.patch_panel)
        else:
            placeholder = QLabel("补丁管理模块不可用\n请确保 mca_core.patch_panel_pyqt 可正常导入")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #a0aec0; font-size: 14px;")
            self.tab_patch_layout.addWidget(placeholder)

    def _on_patch_clicked(self) -> None:
        """切换到补丁管理标签页。"""
        self.tabs.setCurrentWidget(self.tab_patch)

    def _setup_dashboard_tab(self) -> None:
        """设置仪表盘标签页。"""
        self.tab_dashboard = QWidget()
        self.tab_dashboard_layout = QVBoxLayout(self.tab_dashboard)
        self.tab_dashboard_layout.setContentsMargins(0, 0, 0, 0)

        if HAS_DASHBOARD_PANEL:
            if DashboardPanelPyQt is None:
                raise RuntimeError("仪表盘面板模块导入失败")
            self.dashboard_panel = DashboardPanelPyQt(parent=self)
            if DashboardController is not None and self.dashboard_controller is None:
                self.dashboard_controller = DashboardController()
                self.dashboard_controller.start()
            if self.dashboard_controller is not None:
                self.dashboard_panel.set_dashboard(self.dashboard_controller)
                if self.engine and hasattr(self.engine, "set_dashboard_controller"):
                    self.engine.set_dashboard_controller(self.dashboard_controller)
            self.tab_dashboard_layout.addWidget(self.dashboard_panel)
        else:
            placeholder = QLabel("仪表盘模块不可用\n请确保 mca_core.dashboard.dashboard_panel_pyqt 可正常导入")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #a0aec0; font-size: 14px;")
            self.tab_dashboard_layout.addWidget(placeholder)

    def _on_dashboard_clicked(self) -> None:
        """切换到仪表盘标签页。"""
        self.tabs.setCurrentWidget(self.tab_dashboard)

    def _setup_dlc_manager_tab(self) -> None:
        """设置 DLC 管理标签页。"""
        self.tab_dlc_manager = QWidget()
        self.tab_dlc_manager_layout = QVBoxLayout(self.tab_dlc_manager)
        self.tab_dlc_manager_layout.setContentsMargins(0, 0, 0, 0)

        if HAS_DLC_MANAGER:
            if DLCManagerPanelPyQt is None:
                raise RuntimeError("DLC 管理面板模块导入失败")
            self.dlc_manager_panel = DLCManagerPanelPyQt(parent=self)
            if self.brain is not None:
                self.dlc_manager_panel.set_brain(self.brain)
            self.dlc_manager_panel.refresh_requested.connect(self._on_dlc_manager_refresh)
            self.dlc_manager_panel.brain_init_requested.connect(self.start_ai_init_if_needed)
            self.tab_dlc_manager_layout.addWidget(self.dlc_manager_panel)
        else:
            placeholder = QLabel("DLC 管理模块不可用\n请确保 mca_core.dlc_manager_panel_pyqt 可正常导入")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #a0aec0; font-size: 14px;")
            self.tab_dlc_manager_layout.addWidget(placeholder)

    def _on_dlc_manager_clicked(self) -> None:
        """切换到 DLC 管理标签页。"""
        self.tabs.setCurrentWidget(self.tab_dlc_manager)

    def _on_dlc_manager_refresh(self) -> None:
        """DLC 管理面板请求刷新。"""
        if hasattr(self, "dlc_manager_panel") and self.brain is not None:
            self.dlc_manager_panel._refresh()

    def on_settings_clicked(self) -> None:
        """处理设置按钮点击。"""
        from mca_core.python_runtime_optimizer import apply_version_specific_optimizations
        
        dialog = QDialog(self)
        dialog.setWindowTitle("系统设置")
        dialog.resize(520, 300)
        dialog.setStyleSheet(self.styleSheet())
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        
        form_layout = QFormLayout()

        scroll_spin = QSpinBox()
        scroll_spin.setRange(1, 50)
        scroll_spin.setValue(self.config_service.get_scroll_sensitivity())
        form_layout.addRow(QLabel("滚动灵敏度:"), scroll_spin)

        highlight_spin = QSpinBox()
        highlight_spin.setRange(100, 200000)
        highlight_spin.setSingleStep(100)
        highlight_spin.setValue(self.config_service.get_highlight_size_limit())
        form_layout.addRow(QLabel("高亮大小阈值:"), highlight_spin)
        
        mode_combo = QComboBox()
        for mode, desc in MODE_DESCRIPTIONS:
            mode_combo.addItem(f"{mode} - {desc}", mode)
        mode_combo.setCurrentIndex(1)
        form_layout.addRow(QLabel("运行时优化模式:"), mode_combo)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_mode = mode_combo.currentData()
            try:
                self.config_service.set_scroll_sensitivity(scroll_spin.value())
                self.config_service.set_highlight_size_limit(highlight_spin.value())
                self.config_service.save()
                apply_version_specific_optimizations(selected_mode)
                logger.info(f"已应用 {selected_mode} 模式的运行时优化。")
            except Exception as e:
                QMessageBox.warning(self, "设置失败", f"应用优化失败: {str(e)}")

    def load_from_paths(self, paths: list[str]) -> None:
        """从多个路径加载日志（支持压缩包和普通文件）。

        自动识别压缩包，解压并提取日志文件，
        支持同时拖入多个文件合并分析。

        Args:
            paths: 文件路径列表
        """
        import time, threading
        from mca_core.file_io import read_text_limited

        if not paths:
            return

        # 收集日志文件（自动处理压缩包解压）
        log_paths, skipped, temp_dirs = collect_logs_from_paths(paths)

        # 记录临时目录供后续清理
        self._pending_temp_dirs.extend(temp_dirs)

        # 显示跳过信息
        if skipped:
            skipped_msg = "部分文件跳过:\n" + "\n".join(f"  - {s}" for s in skipped[:5])
            if len(skipped) > 5:
                skipped_msg += f"\n  ... 以及其他 {len(skipped) - 5} 条"
            logger.warning(skipped_msg)

        if not log_paths:
            QMessageBox.warning(
                self,
                "未找到日志",
                f"未在选定文件中找到可分析的日志文件。\n\n{skipped_msg}" if skipped else "未找到可分析的日志文件。"
            )
            return

        # 统计信息
        archive_count = len(temp_dirs)
        direct_count = len(log_paths) - sum(
            len([f for f in log_paths if temp_dir in f])
            for temp_dir, _ in temp_dirs
        )
        # 更简单地：解压文件数 vs 直接文件数
        extracted_files = []
        direct_files = []
        for lp in log_paths:
            found = False
            for td, _ in temp_dirs:
                if lp.startswith(td):
                    extracted_files.append(lp)
                    found = True
                    break
            if not found:
                direct_files.append(lp)

        self._set_status_text(f"状态: 正在加载 {len(direct_files)} 个文件 + {len(temp_dirs)} 个压缩包...")

        # 读取所有日志内容
        all_contents: list[str] = []
        for i, log_path in enumerate(log_paths):
            try:
                content = read_text_limited(log_path)
                if content.strip():
                    all_contents.append(f"# 文件: {os.path.basename(log_path)}\n\n{content}")
            except Exception as e:
                logger.warning(f"读取文件失败: {log_path}: {e}")

        if not all_contents:
            QMessageBox.warning(self, "读取失败", "所有日志文件均为空或读取失败。")
            return

        # 合并日志内容
        merged_text = "\n\n" + "=" * 80 + "\n\n".join(all_contents)

        # 显示加载
        self.log_service.set_log_text(merged_text)
        self.file_path = log_paths[0]  # 主文件路径
        self.log_text_edit.setPlainText(merged_text)
        self.btn_analyze.setEnabled(True)
        self.result_text_edit.clear()

        # 状态摘要
        summary_parts = []
        if direct_files:
            summary_parts.append(f"{len(direct_files)} 个文件")
        if temp_dirs:
            summary_parts.append(f"{len(temp_dirs)} 个压缩包")

        total_size = sum(len(c.encode('utf-8')) for c in all_contents)
        self._set_status_text(
            f"状态: 已加载 {', '.join(summary_parts)} "
            f"({len(all_contents)} 篇日志, {total_size / 1024:.1f} KB)"
        )

        # 异步清理旧的临时目录（延迟 30 秒）
        old_temp_dirs = self._pending_temp_dirs[:]
        self._pending_temp_dirs = []
        def _delayed_cleanup():
            time.sleep(30)
            for td, _ in old_temp_dirs:
                cleanup_temp_dir(td)
        threading.Thread(target=_delayed_cleanup, daemon=True).start()

    def on_load_clicked(self) -> None:
        """处理加载按钮点击（支持多文件选择和压缩包）。"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "选择崩溃日志文件或压缩包", "",
            "支持的文件 (*.log *.txt *.zip *.7z *.rar *.tar.gz *.tar *.tar.bz2 *.tar.xz);;"
            "日志文件 (*.log *.txt);;"
            "压缩包 (*.zip *.7z *.rar *.tar.gz *.tar *.tar.bz2 *.tar.xz);;"
            "所有文件 (*.*)"
        )
        if file_paths:
            self.load_from_paths(list(file_paths))

    def load_log_file(self, file_path: str) -> None:
        """
        加载日志文件。
        
        Args:
            file_path: 日志文件路径
        """
        try:
            from mca_core.file_io import read_text_limited
            content = read_text_limited(file_path)
            
            self.log_service.set_log_text(content)
            self.file_path = file_path
            self.log_text_edit.setPlainText(content)
            self._set_status_text(f"状态: 已加载 {os.path.basename(file_path)}")
            self.btn_analyze.setEnabled(True)
            self.result_text_edit.clear()
            self.mod_list_widget.clear()
            if self.graph_canvas is not None:
                self.graph_canvas.figure.clear()
                self.graph_canvas.draw()
        except ValueError as e:
            QMessageBox.critical(self, "文件过大", f"无法加载文件: {e}")
        except Exception as e:
            QMessageBox.critical(self, "加载错误", f"无法加载文件: {e}")

    def import_mods(self) -> None:
        """导入模组列表（后台线程执行文件扫描）。"""
        folder = QFileDialog.getExistingDirectory(self, "选择 .minecraft/mods 文件夹")
        if not folder:
            return

        self.btn_load.setEnabled(False)
        self._set_status_text("状态: 正在扫描模组目录...")

        def _scan_worker() -> None:
            try:
                mods = scan_mods_directory(folder)
                
                def _on_done() -> None:
                    self.current_mods = dict(mods)
                    self.mod_list_widget.clear()
                    self.mod_list_widget.addItem(f"从目录导入 {len(mods)} 个模组:")
                    for modid, versions in sorted(mods.items()):
                        self.mod_list_widget.addItem(f"📦 {modid} (版本: {', '.join(sorted(versions))})")
                    self.tabs.setCurrentIndex(1)
                    self._set_status_text(f"状态: 已导入 {len(mods)} 个模组")
                    self.btn_load.setEnabled(True)
                    QMessageBox.information(self, "导入完成", f"在文件夹中发现 {len(mods)} 个模组。")
                
                QTimer.singleShot(0, _on_done)
            except Exception as e:
                def _on_error() -> None:
                    self.btn_load.setEnabled(True)
                    self._set_status_text("状态: 就绪")
                    QMessageBox.critical(self, "导入失败", f"扫描失败: {e}")
                QTimer.singleShot(0, _on_error)
        
        threading.Thread(target=_scan_worker, daemon=True).start()

    def on_analyze_clicked(self) -> None:
        """处理分析按钮点击。"""
        log_text = self.log_text_edit.toPlainText()
        if not log_text:
            return
            
        self.btn_analyze.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.result_text_edit.clear()
        self.mod_list_widget.clear()
        if self.graph_canvas is not None:
            self.graph_canvas.figure.clear()
            self.graph_canvas.draw()
        
        self.result_text_edit.append("开始执行日志分析...\n" + "="*40)
        self.progress.show()
        self.progress.setValue(0)
        self._set_brain_monitor_state("loading")
        self._set_status_text("状态: 分析中...")
        self.tabs.setCurrentIndex(0)
        
        self.worker = AnalysisWorker(self.engine, self.brain, log_text)
        self.worker.signals.progress.connect(self.on_analysis_progress)
        self.worker.signals.append_log.connect(self.on_analysis_append)
        self.worker.signals.finished.connect(self.on_analysis_finished)
        self.worker.signals.error.connect(self.on_analysis_error)
        self.worker.start()

    def on_analysis_progress(self, val: int, msg: str) -> None:
        """处理分析进度更新。"""
        self.progress.setValue(val)
        self._set_status_text(f"状态: {msg}")

    def on_analysis_append(self, msg: str) -> None:
        """处理分析日志追加。"""
        self.result_text_edit.append(msg)

    def on_analysis_finished(
        self,
        result_text: str,
        dep_pairs: set[tuple[str, str]],
        mods: dict[str, set],
        cause_counts: dict[str, int]
    ) -> None:
        """处理分析完成。"""
        self.current_dep_pairs = set(dep_pairs or set())
        self.current_mods = dict(mods or {})
        self.current_cause_counts = dict(cause_counts or {})

        self.result_text_edit.append("\n" + "=" * 60)
        self.result_text_edit.append("  MCA 诊断分析结果")
        self.result_text_edit.append("=" * 60 + "\n")
        self.result_text_edit.append(result_text)
        
        self.mod_list_widget.addItem(f"检测到 {len(mods)} 个独立模组:")
        for modid, vers in sorted(mods.items()):
            v_str = ", ".join(vers)
            self.mod_list_widget.addItem(f"{modid} (版本: {v_str})")
            
        self.draw_graphs(dep_pairs, cause_counts)
        self.refresh_hardware_analysis()
        
        self.finish_analysis()
        self._set_brain_monitor_state("active")
        self._set_status_text("状态: 分析完成！")

    def draw_graphs(
        self,
        dep_pairs: set[tuple[str, str]],
        cause_counts: dict[str, int]
    ) -> None:
        """绘制图表。"""
        if not self._ensure_graph_canvas():
            return

        if not HAS_NX or nx is None:
            return

        fig = self.graph_canvas.figure
        fig.clear()
        
        if cause_counts:
            ax = fig.add_subplot(121)
            ax.set_title("崩溃原因统计", fontdict={'family': 'SimHei' if sys.platform == 'win32' else 'sans-serif'})
            labels = list(cause_counts.keys())
            sizes = list(cause_counts.values())
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=['#4fd1c5', '#f6ad55', '#fc8181', '#f687b3'])
            ax.axis('equal')
            ax2 = fig.add_subplot(122)
        else:
            ax2 = fig.add_subplot(111)
            
        ax2.set_title("核心依赖关系网络", fontdict={'family': 'SimHei' if sys.platform == 'win32' else 'sans-serif'})
        if dep_pairs:
            G, pos = build_nx_graph(dep_pairs, self.graph_layout_name, self.filter_isolated_nodes)
            if G is not None and pos is not None:
                nx.draw(G, pos, ax=ax2, with_labels=True, node_color='#d1d9e6', 
                        node_size=800, font_size=8, font_weight='bold', edge_color='#a0aec0',
                        arrowsize=10, font_family='Consolas')
        else:
            ax2.text(0.5, 0.5, "未检测到明确的依赖问题", ha='center', va='center', color='#718096')
            ax2.axis('off')
            
        fig.tight_layout()
        self.graph_canvas.draw()

    def on_analysis_error(self, err_msg: str) -> None:
        """处理分析错误。"""
        self.result_text_edit.append(f"\n[错误] 分析过程中断: {err_msg}")
        self.finish_analysis()
        self._set_brain_monitor_state("error")
        self._set_status_text("状态: 分析出错")

    def finish_analysis(self) -> None:
        """完成分析。"""
        self.btn_analyze.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.progress.hide()
