# -*- coding: utf-8 -*-
"""MCA DLC 管理 — PyQt6 管理面板

提供 DLC 生命周期管理可视化界面，包括 DLC 列表、状态指示、
依赖查看、启用/禁用/挂起/恢复操作和操作日志。
"""
from __future__ import annotations

import inspect
import logging
import os
import threading
from datetime import datetime
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))

DLC_STATE_COLORS: dict[str, str] = {
    "unloaded": "#a0aec0",
    "loading": "#4299e1",
    "loaded": "#48bb78",
    "initialized": "#319795",
    "active": "#2ea043",
    "suspended": "#ecc94b",
    "disabled": "#718096",
    "failed": "#f56565",
}

DLC_STATE_LABELS: dict[str, str] = {
    "unloaded": "未加载",
    "loading": "加载中",
    "loaded": "已加载",
    "initialized": "已初始化",
    "active": "运行中",
    "suspended": "已挂起",
    "disabled": "已禁用",
    "failed": "失败",
}


class DLCStateIndicator(QWidget):
    """DLC 状态指示灯。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor("#a0aec0")
        self.setFixedSize(12, 12)

    def set_state(self, state: str) -> None:
        self._color = QColor(DLC_STATE_COLORS.get(state, "#a0aec0"))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(self._color.darker(120))
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()


class DLCManagerPanelPyQt(QWidget):
    """DLC 管理面板。

    提供 DLC 列表视图、状态管理操作、依赖关系查看
    和操作日志功能。
    """

    refresh_requested = pyqtSignal()
    brain_init_requested = pyqtSignal()
    _log_signal = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._brain: Any = None
        self._refresh_timer: Optional[QTimer] = None
        self._selected_dlc_name: Optional[str] = None
        self._log_lines: list[str] = []
        self._brain_connected: bool = False
        self._setup_ui()
        self._log_signal.connect(self._on_log_message)

    def set_brain(self, brain: Any) -> None:
        """设置关联的 BrainCore 实例。"""
        self._brain = brain
        self._brain_connected = brain is not None
        if brain is not None:
            self._log("分析引擎已连接")
        self._switch_view()
        self._start_auto_refresh()
        self._refresh()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._setup_toolbar(layout)
        self._setup_content_stack(layout)
        self._setup_log_area(layout)

    def _setup_toolbar(self, layout: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        title = QLabel("DLC 管理")
        title.setObjectName("h2")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self._btn_load = QPushButton("加载 DLC")
        self._btn_load.setObjectName("toolbarBtn")
        self._btn_load.clicked.connect(self._on_load_dlc)
        toolbar.addWidget(self._btn_load)

        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.setObjectName("smallBtn")
        self._btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(self._btn_refresh)

        self._auto_refresh = QCheckBox("自动刷新")
        self._auto_refresh.setChecked(True)
        self._auto_refresh.toggled.connect(self._toggle_auto_refresh)
        toolbar.addWidget(self._auto_refresh)

        layout.addLayout(toolbar)

    def _setup_content_stack(self, layout: QVBoxLayout) -> None:
        """使用 QStackedWidget 在「未连接」和「正常」视图之间切换。"""
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self._create_no_brain_view())
        self._content_stack.addWidget(self._create_main_area())
        self._content_stack.setCurrentIndex(0)
        layout.addWidget(self._content_stack, stretch=1)

    def _create_no_brain_view(self) -> QWidget:
        """未连接分析引擎时的占位视图。"""
        container = QFrame()
        container.setObjectName("siliconeCard")
        vbox = QVBoxLayout(container)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("分析引擎未就绪")
        title.setObjectName("h3")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(title, alignment=Qt.AlignmentFlag.AlignCenter)

        desc = QLabel("请先初始化语义分析引擎后再使用 DLC 管理功能。")
        desc.setObjectName("body-sm")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(desc, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_init = QPushButton("初始化分析引擎")
        btn_init.setMinimumSize(200, 42)
        btn_init.setObjectName("primaryBtn")
        btn_init.clicked.connect(self._on_init_brain)
        vbox.addWidget(btn_init, alignment=Qt.AlignmentFlag.AlignCenter)

        hint = QLabel(
            "或点击顶部工具栏的「语义分析」按钮激活引擎。\n"
            "引擎激活后 DLC 将自动列于此处。"
        )
        hint.setObjectName("caption")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.addWidget(hint, alignment=Qt.AlignmentFlag.AlignCenter)

        return container

    def _create_main_area(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = self._create_dlc_list_panel()
        right_panel = self._create_detail_panel()

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([500, 350])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        return splitter

    def _create_dlc_list_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("siliconeCard")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(4, 4, 4, 4)

        self._dlc_table = QTableWidget()
        self._dlc_table.setColumnCount(7)
        self._dlc_table.setHorizontalHeaderLabels([
            "状态", "名称", "版本", "类型", "运行状态", "优先级", "依赖数",
        ])
        self._dlc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._dlc_table.setColumnWidth(0, 50)
        self._dlc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._dlc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._dlc_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._dlc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._dlc_table.setAlternatingRowColors(True)
        self._dlc_table.clicked.connect(self._on_dlc_selected)
        panel_layout.addWidget(self._dlc_table)

        summary = QLabel("")
        summary.setObjectName("caption")
        self._summary_label = summary
        panel_layout.addWidget(summary)

        return panel

    def _create_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("siliconeCard")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(6, 6, 6, 6)
        panel_layout.setSpacing(4)

        heading = QLabel("DLC 详情")
        heading.setObjectName("sectionHeader")
        panel_layout.addWidget(heading)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        info_tab = QWidget()
        info_lo = QVBoxLayout(info_tab)
        info_lo.setContentsMargins(4, 4, 4, 4)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; border: none; background: transparent;"
        )
        info_lo.addWidget(self._detail_text)

        dep_tab = QWidget()
        dep_lo = QVBoxLayout(dep_tab)
        dep_lo.setContentsMargins(4, 4, 4, 4)
        self._dep_tree = QTreeWidget()
        self._dep_tree.setHeaderLabels(["依赖项", "状态"])
        dep_lo.addWidget(self._dep_tree)

        action_tab = QWidget()
        action_lo = QVBoxLayout(action_tab)
        action_lo.setContentsMargins(4, 8, 4, 4)
        action_lo.setSpacing(6)

        row1 = QHBoxLayout()
        self._btn_enable = QPushButton("启用")
        self._btn_enable.setObjectName("accentButton")
        self._btn_enable.clicked.connect(self._on_enable_dlc)
        row1.addWidget(self._btn_enable)

        self._btn_disable = QPushButton("禁用")
        self._btn_disable.setObjectName("toolbarBtn")
        self._btn_disable.clicked.connect(self._on_disable_dlc)
        row1.addWidget(self._btn_disable)

        self._btn_suspend = QPushButton("挂起")
        self._btn_suspend.setObjectName("warningBtn")
        self._btn_suspend.clicked.connect(self._on_suspend_dlc)
        row1.addWidget(self._btn_suspend)

        self._btn_resume = QPushButton("恢复")
        self._btn_resume.setObjectName("successBtn")
        self._btn_resume.clicked.connect(self._on_resume_dlc)
        row1.addWidget(self._btn_resume)
        action_lo.addLayout(row1)

        row2 = QHBoxLayout()
        self._btn_reload = QPushButton("重新加载")
        self._btn_reload.setObjectName("toolbarBtn")
        self._btn_reload.clicked.connect(self._on_reload_dlc)
        row2.addWidget(self._btn_reload)

        self._btn_unregister = QPushButton("注销")
        self._btn_unregister.setObjectName("dangerBtn")
        self._btn_unregister.clicked.connect(self._on_unregister_dlc)
        row2.addWidget(self._btn_unregister)
        action_lo.addLayout(row2)

        action_lo.addStretch()

        tabs.addTab(info_tab, "详情")
        tabs.addTab(dep_tab, "依赖关系")
        tabs.addTab(action_tab, "操作")

        self._update_action_buttons()
        panel_layout.addWidget(tabs)
        return panel

    def _setup_log_area(self, layout: QVBoxLayout) -> None:
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 4, 4, 4)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; border: none; background: transparent;"
        )
        log_layout.addWidget(self._log_text)

        layout.addWidget(log_group)

    # ------------------------------------------------------------------
    # 视图切换
    # ------------------------------------------------------------------

    def _switch_view(self) -> None:
        """根据 brain 是否连接切换内容区视图。"""
        self._content_stack.setCurrentIndex(1 if self._brain_connected else 0)

    # ------------------------------------------------------------------
    # 定时刷新
    # ------------------------------------------------------------------

    def _start_auto_refresh(self) -> None:
        if self._refresh_timer is None:
            self._refresh_timer = QTimer(self)
            self._refresh_timer.timeout.connect(self._refresh)
        if hasattr(self, "_auto_refresh"):
            if self._auto_refresh.isChecked():
                self._refresh_timer.start(10000)
            else:
                self._refresh_timer.stop()
        else:
            self._refresh_timer.start(10000)

    def _toggle_auto_refresh(self, checked: bool) -> None:
        if self._refresh_timer:
            if checked:
                self._refresh_timer.start(10000)
            else:
                self._refresh_timer.stop()

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        self._log_signal.emit(message)

    def _on_log_message(self, message: str) -> None:
        self._log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        if len(self._log_lines) > 200:
            self._log_lines = self._log_lines[-200:]
        self._log_text.setPlainText("\n".join(self._log_lines))
        self._log_text.moveCursor(self._log_text.textCursor().MoveOperation.End)

    # ------------------------------------------------------------------
    # 数据刷新
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._brain is None:
            return
        self._refresh_dlc_list()

    def _refresh_dlc_list(self) -> None:
        try:
            status = self._brain.get_dlc_status()
            dlcs = self._brain.dlcs

            self._dlc_table.setRowCount(len(dlcs))

            summary_parts: list[str] = []
            state_counts: dict[str, int] = {}

            for row, (name, dlc) in enumerate(dlcs.items()):
                info = status.get(name, {})
                dlc_state = dlc.state.value if hasattr(dlc, "state") else "unknown"
                dlc_version = info.get("version", "-")
                dlc_type = info.get("type", "-")
                dlc_priority = str(info.get("priority", "auto"))

                state_counts[dlc_state] = state_counts.get(dlc_state, 0) + 1

                indicator = DLCStateIndicator()
                indicator.set_state(dlc_state)
                self._dlc_table.setCellWidget(row, 0, indicator)

                self._dlc_table.setItem(row, 1, QTableWidgetItem(name))
                self._dlc_table.setItem(row, 2, QTableWidgetItem(dlc_version))
                self._dlc_table.setItem(row, 3, QTableWidgetItem(dlc_type))

                state_label = DLC_STATE_LABELS.get(dlc_state, dlc_state)
                state_item = QTableWidgetItem(state_label)
                state_item.setForeground(QColor(DLC_STATE_COLORS.get(dlc_state, "#a0aec0")))
                self._dlc_table.setItem(row, 4, state_item)

                self._dlc_table.setItem(row, 5, QTableWidgetItem(dlc_priority))

                dep_count = len(info.get("dependencies", []))
                self._dlc_table.setItem(row, 6, QTableWidgetItem(str(dep_count)))

            self._dlc_table.resizeColumnsToContents()
            self._dlc_table.setColumnWidth(1, 180)

            for state, count in sorted(state_counts.items()):
                label = DLC_STATE_LABELS.get(state, state)
                summary_parts.append(f"{label}: {count}")

            self._summary_label.setText(f"共 {len(dlcs)} 个 DLC  |  " + "  |  ".join(summary_parts))

            if self._selected_dlc_name and self._selected_dlc_name in dlcs:
                self._refresh_detail(self._selected_dlc_name)
            self._update_action_buttons()
        except Exception as e:
            self._log(f"刷新失败: {e}")

    # ------------------------------------------------------------------
    # DLC 选中 & 详情
    # ------------------------------------------------------------------

    def _on_dlc_selected(self, index) -> None:
        try:
            row = index.row()
            name = self._dlc_table.item(row, 1).text()
            self._selected_dlc_name = name
            self._refresh_detail(name)
            self._update_action_buttons()
        except Exception:
            pass

    def _refresh_detail(self, name: str) -> None:
        if self._brain is None:
            return
        dlc = self._brain.dlcs.get(name)
        if dlc is None:
            return

        try:
            manifest = dlc.get_manifest()
            dlc_state = dlc.state.value if hasattr(dlc, "state") else "unknown"
            state_label = DLC_STATE_LABELS.get(dlc_state, dlc_state)
            initialized = bool(getattr(dlc, "_initialized", False))

            detail = (
                f"名称: {manifest.name}\n"
                f"版本: {manifest.version}\n"
                f"作者: {manifest.author}\n"
                f"描述: {manifest.description}\n"
                f"类型: {manifest.dlc_type.value}\n"
                f"状态: {state_label}\n"
                f"已初始化: {'是' if initialized else '否'}\n"
                f"启用: {'是' if getattr(dlc, 'enabled', False) else '否'}\n"
                f"优先级: {manifest.priority}\n"
            )
            self._detail_text.setPlainText(detail)

            self._dep_tree.clear()
            for dep_raw in manifest.dependencies:
                dep_name = dep_raw
                if ">=" in dep_raw:
                    dep_name = dep_raw.split(">=")[0].strip()
                elif "==" in dep_raw:
                    dep_name = dep_raw.split("==")[0].strip()
                elif "~=" in dep_raw:
                    dep_name = dep_raw.split("~=")[0].strip()

                dep_dlc = self._brain.dlcs.get(dep_name)
                dep_state: str
                if dep_dlc is None:
                    if dep_name in ("Brain Core", "BrainCore", "core", getattr(self._brain, "name", "")):
                        dep_state = "核心 (已就绪)"
                    else:
                        dep_state = "未加载"
                else:
                    dep_dlc_state = dep_dlc.state.value if hasattr(dep_dlc, "state") else "unknown"
                    dep_state = DLC_STATE_LABELS.get(dep_dlc_state, dep_dlc_state)

                item = QTreeWidgetItem([dep_name, dep_state])
                item.setToolTip(0, dep_raw)
                self._dep_tree.addTopLevelItem(item)
        except Exception as e:
            self._detail_text.setPlainText(f"获取详情失败: {e}")

    # ------------------------------------------------------------------
    # 操作按钮
    # ------------------------------------------------------------------

    def _update_action_buttons(self) -> None:
        has_brain = self._brain is not None
        has_selection = self._selected_dlc_name is not None
        self._btn_load.setEnabled(has_brain)
        self._btn_enable.setEnabled(has_selection and has_brain)
        self._btn_disable.setEnabled(has_selection and has_brain)
        self._btn_suspend.setEnabled(has_selection and has_brain)
        self._btn_resume.setEnabled(has_selection and has_brain)
        self._btn_reload.setEnabled(has_selection and has_brain)
        self._btn_unregister.setEnabled(has_selection and has_brain)

        if has_selection and has_brain:
            dlc = self._brain.dlcs.get(self._selected_dlc_name)
            if dlc is not None:
                dlc_state = dlc.state.value if hasattr(dlc, "state") else ""
                self._btn_enable.setEnabled(dlc_state in ("disabled", "failed"))
                self._btn_disable.setEnabled(dlc_state in ("active", "initialized", "suspended"))
                self._btn_suspend.setEnabled(dlc_state == "active")
                self._btn_resume.setEnabled(dlc_state == "suspended")

    # ------------------------------------------------------------------
    # 初始化引擎（发射信号给主窗口处理）
    # ------------------------------------------------------------------

    def _on_init_brain(self) -> None:
        """用户点击「初始化分析引擎」按钮。"""
        self._log("正在请求初始化分析引擎...")
        self.brain_init_requested.emit()

    # ------------------------------------------------------------------
    # DLC 生命周期操作
    # ------------------------------------------------------------------

    def _on_enable_dlc(self) -> None:
        if self._brain is None or self._selected_dlc_name is None:
            return
        try:
            if self._brain.enable_dlc(self._selected_dlc_name):
                self._log(f"已启用 DLC: {self._selected_dlc_name}")
            else:
                self._log(f"启用 DLC 失败: {self._selected_dlc_name}")
        except Exception as e:
            self._log(f"启用 DLC 异常: {e}")
        self._refresh()

    def _on_disable_dlc(self) -> None:
        if self._brain is None or self._selected_dlc_name is None:
            return
        try:
            if self._brain.disable_dlc(self._selected_dlc_name):
                self._log(f"已禁用 DLC: {self._selected_dlc_name}")
            else:
                self._log(f"禁用 DLC 失败: {self._selected_dlc_name}")
        except Exception as e:
            self._log(f"禁用 DLC 异常: {e}")
        self._refresh()

    def _on_suspend_dlc(self) -> None:
        if self._brain is None or self._selected_dlc_name is None:
            return
        try:
            if self._brain.suspend_dlc(self._selected_dlc_name):
                self._log(f"已挂起 DLC: {self._selected_dlc_name}")
            else:
                self._log(f"挂起 DLC 失败: {self._selected_dlc_name}")
        except Exception as e:
            self._log(f"挂起 DLC 异常: {e}")
        self._refresh()

    def _on_resume_dlc(self) -> None:
        if self._brain is None or self._selected_dlc_name is None:
            return
        try:
            if self._brain.resume_dlc(self._selected_dlc_name):
                self._log(f"已恢复 DLC: {self._selected_dlc_name}")
            else:
                self._log(f"恢复 DLC 失败: {self._selected_dlc_name}")
        except Exception as e:
            self._log(f"恢复 DLC 异常: {e}")
        self._refresh()

    def _on_reload_dlc(self) -> None:
        if self._brain is None or self._selected_dlc_name is None:
            return
        reply = QMessageBox.question(
            self,
            "确认重新加载",
            f"确定要重新加载 DLC \"{self._selected_dlc_name}\" 吗？\n这将先注销再重新加载。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        dlc_name = self._selected_dlc_name
        dlc = self._brain.dlcs.get(dlc_name)

        dlc_file_path: str | None = None
        if dlc is not None:
            try:
                dlc_file_path = inspect.getfile(type(dlc))
            except Exception:
                pass

        try:
            self._brain.unregister_dlc(dlc_name)
        except Exception as e:
            self._log(f"注销 DLC 失败: {e}")
            self._selected_dlc_name = None
            self._refresh()
            return

        self._log(f"已注销 DLC: {dlc_name}")

        try:
            if dlc_file_path and os.path.isfile(dlc_file_path):
                count = self._brain.load_dlc_file(dlc_file_path, allow_replace=True)
                if count > 0:
                    self._log(f"已重新加载 DLC: {dlc_name} (from {os.path.basename(dlc_file_path)})")
                else:
                    self._log(f"重新加载 DLC 失败: {dlc_name} (文件可能无有效 DLC 类)")
            else:
                self._log(f"无法定位 DLC 源文件，仅完成注销: {dlc_name}")
        except Exception as e:
            self._log(f"重新加载 DLC 异常: {e}")

        self._selected_dlc_name = None
        self._refresh()

    def _on_unregister_dlc(self) -> None:
        if self._brain is None or self._selected_dlc_name is None:
            return
        reply = QMessageBox.warning(
            self,
            "确认注销",
            f"确定要注销 DLC \"{self._selected_dlc_name}\" 吗？\n注销后需要重新加载才能恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._brain.unregister_dlc(self._selected_dlc_name)
            self._log(f"已注销 DLC: {self._selected_dlc_name}")
            self._selected_dlc_name = None
            self._detail_text.clear()
            self._dep_tree.clear()
            self._update_action_buttons()
        except Exception as e:
            self._log(f"注销失败: {e}")
        self._refresh()

    def _on_load_dlc(self) -> None:
        if self._brain is None:
            reply = QMessageBox.question(
                self,
                "引擎未就绪",
                "分析引擎未初始化，无法加载 DLC。\n\n是否立即初始化分析引擎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_init_brain()
            return

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 DLC 文件",
            os.path.join(ROOT_DIR, "src", "dlcs"),
            "Python 文件 (*.py);;所有文件 (*.*)",
        )
        if not file_paths:
            return

        self._log("正在发现 DLC 类...")
        self._pending_dlc_discoveries: list[tuple[str, type]] = []

        def _discover_worker() -> None:
            from brain_system.discovery import load_dlc_classes_from_file
            from pathlib import Path

            for fp in file_paths:
                try:
                    classes = load_dlc_classes_from_file(Path(fp))
                    for cls in classes:
                        self._pending_dlc_discoveries.append((fp, cls))
                except Exception as e:
                    self._log_signal.emit(f"发现 DLC 类失败 {os.path.basename(fp)}: {e}")

            QTimer.singleShot(0, self._on_dlc_discovery_complete)

        threading.Thread(target=_discover_worker, daemon=True).start()

    def _on_dlc_discovery_complete(self) -> None:
        try:
            for fp, cls in self._pending_dlc_discoveries:
                try:
                    inst = cls(self._brain)
                    self._brain.register_dlc(inst)
                    self._log(f"已加载 DLC: {inst.get_manifest().name} (from {os.path.basename(fp)})")
                except Exception as e:
                    self._log(f"注册 DLC 失败 {os.path.basename(fp)}: {e}")
        finally:
            self._pending_dlc_discoveries.clear()
            self.refresh_requested.emit()


def create_dlc_manager_panel(brain: Any = None) -> DLCManagerPanelPyQt:
    """创建 DLC 管理面板。"""
    panel = DLCManagerPanelPyQt()
    if brain:
        panel.set_brain(brain)
    return panel