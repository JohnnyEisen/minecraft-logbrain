# -*- coding: utf-8 -*-
"""MCA 仪表盘 — PyQt6 监控面板

提供检测器性能监控的可视化界面，包括状态指示灯、性能图表、
告警列表和趋势分析。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QSlider,
    QDoubleSpinBox,
    QFormLayout,
    QCheckBox,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))

STATUS_COLORS = {
    "online": "#48bb78",
    "offline": "#a0aec0",
    "degraded": "#ecc94b",
    "unknown": "#a0aec0",
}

ALERT_COLORS = {
    "info": "#4299e1",
    "warning": "#ecc94b",
    "error": "#f56565",
    "critical": "#9b2c2c",
}

TREND_COLORS = {
    "stable": "#48bb78",
    "increasing": "#f56565",
    "decreasing": "#4299e1",
    "improving": "#48bb78",
    "declining": "#f56565",
    "slightly_volatile": "#ecc94b",
    "volatile": "#f56565",
}


class StatusIndicator(QWidget):
    """状态指示灯组件。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor("#a0aec0")
        self.setFixedSize(12, 12)

    def set_status(self, status: str) -> None:
        color = STATUS_COLORS.get(status, "#a0aec0")
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import QPainter, QBrush, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._color))
        painter.setPen(QPen(self._color.darker(120), 1))
        radius = min(self.width(), self.height()) // 2 - 1
        painter.drawEllipse(1, 1, radius * 2, radius * 2)
        painter.end()


class SimpleBarWidget(QWidget):
    """简易柱状图组件。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._max_value: float = 1.0
        self._bar_color = QColor("#4299e1")
        self.setMinimumHeight(80)

    def set_values(self, values: list[float], bar_color: str = "#4299e1") -> None:
        self._values = values
        self._max_value = max(values) if values else 1.0
        self._bar_color = QColor(bar_color)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._values:
            painter.end()
            return

        bar_count = len(self._values)
        bar_width = max(3, (self.width() - (bar_count + 1) * 2) // bar_count)
        spacing = 2

        for i, val in enumerate(self._values):
            x = i * (bar_width + spacing) + spacing
            h = 0
            if self._max_value > 0:
                h = int((val / self._max_value) * (self.height() - 4))
            y = self.height() - h - 2
            painter.fillRect(x, y, bar_width, h, self._bar_color)
        painter.end()


class DashboardPanelPyQt(QWidget):
    """仪表盘 PyQt6 面板。

    提供检测器状态总览、性能指标表格、告警列表、
    阈值配置和历史趋势标签页。
    """

    refresh_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._dashboard = None
        self._refresh_timer: Optional[QTimer] = None
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._filter_text = ""
        self._setup_ui()

    def set_dashboard(self, dashboard) -> None:
        """设置关联的仪表盘 DLC 实例。"""
        self._dashboard = dashboard
        self._start_auto_refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._setup_toolbar(layout)
        self._setup_tabs(layout)

    def _setup_toolbar(self, layout: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        title = QLabel("检测器仪表盘")
        title.setObjectName("h2")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self._filter_input = QComboBox()
        self._filter_input.setEditable(True)
        self._filter_input.setPlaceholderText("筛选检测器...")
        self._filter_input.setMinimumWidth(180)
        self._filter_input.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._filter_input)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["按名称", "按状态", "按响应时间", "按成功率", "按稳定性"])
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar.addWidget(self._sort_combo)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("smallBtn")
        btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(btn_refresh)

        self._auto_refresh = QCheckBox("自动刷新")
        self._auto_refresh.setChecked(True)
        self._auto_refresh.toggled.connect(self._toggle_auto_refresh)
        toolbar.addWidget(self._auto_refresh)

        layout.addLayout(toolbar)

    def _setup_tabs(self, layout: QVBoxLayout) -> None:
        self._tabs = QTabWidget()

        self._tab_overview = self._create_overview_tab()
        self._tab_detectors = self._create_detectors_tab()
        self._tab_alerts = self._create_alerts_tab()
        self._tab_trends = self._create_trends_tab()
        self._tab_settings = self._create_settings_tab()

        self._tabs.addTab(self._tab_overview, "总览")
        self._tabs.addTab(self._tab_detectors, "检测器")
        self._tabs.addTab(self._tab_alerts, "告警")
        self._tabs.addTab(self._tab_trends, "趋势")
        self._tabs.addTab(self._tab_settings, "阈值")

        layout.addWidget(self._tabs)

    def _create_overview_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        summary_heading = QLabel("系统状态总览")
        summary_heading.setObjectName("sectionHeader")
        layout.addWidget(summary_heading)

        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(12)

        self._lbl_total = QLabel("检测器总数: --")
        self._lbl_total.setObjectName("body")
        self._lbl_online = QLabel("在线: --")
        self._lbl_online.setObjectName("body")
        self._lbl_offline = QLabel("离线: --")
        self._lbl_offline.setObjectName("body")
        self._lbl_degraded = QLabel("降级: --")
        self._lbl_degraded.setObjectName("body")
        self._lbl_avg_rt = QLabel("平均响应: --ms")
        self._lbl_avg_rt.setObjectName("body")
        self._lbl_success = QLabel("成功率: --%")
        self._lbl_success.setObjectName("body")
        self._lbl_stability = QLabel("稳定性: --")
        self._lbl_stability.setObjectName("body")

        for lbl in [self._lbl_total, self._lbl_online, self._lbl_offline, self._lbl_degraded,
                     self._lbl_avg_rt, self._lbl_success, self._lbl_stability]:
            summary_layout.addWidget(lbl)

        summary_layout.addStretch()
        layout.addLayout(summary_layout)

        chart_heading = QLabel("性能概览")
        chart_heading.setObjectName("sectionHeader")
        layout.addWidget(chart_heading)

        chart_layout = QHBoxLayout()
        chart_layout.setSpacing(12)
        self._throughput_chart = SimpleBarWidget()
        self._response_chart = SimpleBarWidget()
        throughput_label = QLabel("吞吐量")
        throughput_label.setObjectName("caption")
        response_label = QLabel("响应时间")
        response_label.setObjectName("caption")
        chart_layout.addWidget(throughput_label)
        chart_layout.addWidget(self._throughput_chart)
        chart_layout.addWidget(response_label)
        chart_layout.addWidget(self._response_chart)
        layout.addLayout(chart_layout)

        self._overview_text = QTextEdit()
        self._overview_text.setReadOnly(True)
        self._overview_text.setMaximumHeight(100)
        layout.addWidget(self._overview_text)

        return tab

    def _create_detectors_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._det_table = QTableWidget()
        self._det_table.setColumnCount(9)
        self._det_table.setHorizontalHeaderLabels([
            "状态", "检测器名称", "优先级", "运行次数", "成功率",
            "响应时间(ms)", "检测率", "误报率", "稳定性",
        ])
        self._det_table.horizontalHeader().setStretchLastSection(True)
        self._det_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._det_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._det_table.setAlternatingRowColors(True)
        self._det_table.clicked.connect(self._on_detector_selected)
        layout.addWidget(self._det_table)

        self._det_detail = QTextEdit()
        self._det_detail.setReadOnly(True)
        self._det_detail.setMaximumHeight(100)
        layout.addWidget(self._det_detail)

        return tab

    def _create_alerts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        alert_toolbar = QHBoxLayout()
        self._alert_filter = QComboBox()
        self._alert_filter.addItems(["全部", "info", "warning", "error", "critical"])
        self._alert_filter.currentTextChanged.connect(self._refresh)
        alert_toolbar.addWidget(QLabel("级别:"))
        alert_toolbar.addWidget(self._alert_filter)

        btn_ack = QPushButton("确认选中")
        btn_ack.clicked.connect(self._acknowledge_selected)
        alert_toolbar.addWidget(btn_ack)

        btn_resolve = QPushButton("解决选中")
        btn_resolve.clicked.connect(self._resolve_selected)
        alert_toolbar.addWidget(btn_resolve)

        alert_toolbar.addStretch()
        layout.addLayout(alert_toolbar)

        self._alert_table = QTableWidget()
        self._alert_table.setColumnCount(6)
        self._alert_table.setHorizontalHeaderLabels([
            "级别", "检测器", "类型", "消息", "时间", "已确认",
        ])
        self._alert_table.horizontalHeader().setStretchLastSection(True)
        self._alert_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._alert_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._alert_table)

        return tab

    def _create_trends_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        trend_toolbar = QHBoxLayout()
        self._trend_detector = QComboBox()
        self._trend_detector.setMinimumWidth(200)
        self._trend_detector.currentTextChanged.connect(self._refresh_trend)
        trend_toolbar.addWidget(QLabel("检测器:"))
        trend_toolbar.addWidget(self._trend_detector)

        self._trend_range = QComboBox()
        self._trend_range.addItems(["1h", "6h", "24h", "7d"])
        self._trend_range.currentTextChanged.connect(self._refresh_trend)
        trend_toolbar.addWidget(QLabel("时间范围:"))
        trend_toolbar.addWidget(self._trend_range)
        trend_toolbar.addStretch()
        layout.addLayout(trend_toolbar)

        self._trend_chart = SimpleBarWidget()
        self._trend_chart.setMinimumHeight(120)
        layout.addWidget(self._trend_chart)

        self._trend_text = QTextEdit()
        self._trend_text.setReadOnly(True)
        layout.addWidget(self._trend_text)

        return tab

    def _create_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)

        self._spin_max_rt = QDoubleSpinBox()
        self._spin_max_rt.setRange(100, 60000)
        self._spin_max_rt.setValue(5000)
        self._spin_max_rt.setSuffix(" ms")
        layout.addRow("最大响应时间:", self._spin_max_rt)

        self._spin_min_success = QDoubleSpinBox()
        self._spin_min_success.setRange(0.1, 1.0)
        self._spin_min_success.setSingleStep(0.05)
        self._spin_min_success.setValue(0.8)
        layout.addRow("最小成功率:", self._spin_min_success)

        self._spin_max_fp = QDoubleSpinBox()
        self._spin_max_fp.setRange(0.05, 1.0)
        self._spin_max_fp.setSingleStep(0.05)
        self._spin_max_fp.setValue(0.3)
        layout.addRow("最大误报率:", self._spin_max_fp)

        self._spin_max_idle = QDoubleSpinBox()
        self._spin_max_idle.setRange(10, 3600)
        self._spin_max_idle.setValue(300)
        self._spin_max_idle.setSuffix(" 秒")
        layout.addRow("最大空闲时间:", self._spin_max_idle)

        self._spin_throughput_drop = QDoubleSpinBox()
        self._spin_throughput_drop.setRange(0.1, 0.9)
        self._spin_throughput_drop.setSingleStep(0.1)
        self._spin_throughput_drop.setValue(0.5)
        layout.addRow("吞吐量骤降比例:", self._spin_throughput_drop)

        self._spin_accuracy_drop = QDoubleSpinBox()
        self._spin_accuracy_drop.setRange(0.1, 0.9)
        self._spin_accuracy_drop.setSingleStep(0.1)
        self._spin_accuracy_drop.setValue(0.3)
        layout.addRow("准确率骤降比例:", self._spin_accuracy_drop)

        btn_save = QPushButton("应用阈值")
        btn_save.clicked.connect(self._save_thresholds)
        layout.addRow("", btn_save)

        return tab

    def _start_auto_refresh(self) -> None:
        if self._refresh_timer is None:
            self._refresh_timer = QTimer(self)
            self._refresh_timer.timeout.connect(self._refresh_visible)
        if hasattr(self, "_auto_refresh"):
            if self._auto_refresh.isChecked():
                self._refresh_timer.start(3000)
            else:
                self._refresh_timer.stop()
        else:
            self._refresh_timer.start(3000)

    def _toggle_auto_refresh(self, checked: bool) -> None:
        if self._refresh_timer:
            if checked:
                self._refresh_timer.start(3000)
            else:
                self._refresh_timer.stop()

    def _refresh_visible(self) -> None:
        if self._dashboard is None:
            return
        self._refresh_overview()
        current = self._tabs.currentIndex() if hasattr(self, "_tabs") else 0
        if current == 1:
            self._refresh_detectors()
        elif current == 2:
            self._refresh_alerts()
        elif current == 3:
            self._refresh_trend()

    def _refresh(self) -> None:
        if self._dashboard is None:
            return
        self._refresh_overview()
        self._refresh_detectors()
        self._refresh_alerts()
        self._refresh_trend()

    def _refresh_overview(self) -> None:
        try:
            summary = self._dashboard.get_aggregated_summary()
            self._lbl_total.setText(f"检测器总数: {summary['total_detectors']}")
            self._lbl_online.setText(f"在线: {summary['online']}")
            self._lbl_offline.setText(f"离线: {summary['offline']}")
            self._lbl_degraded.setText(f"降级: {summary['degraded']}")
            self._lbl_avg_rt.setText(f"平均响应: {summary['avg_response_time_ms']:.1f}ms")
            self._lbl_success.setText(f"成功率: {summary['avg_success_rate']*100:.1f}%")
            self._lbl_stability.setText(f"稳定性: {summary['overall_stability']:.2f}")

            all_metrics = self._dashboard.get_all_metrics()
            throughputs = [m.get("throughput_per_second", 0) for m in all_metrics.values()]
            response_times = [m.get("avg_response_time_ms", 0) for m in all_metrics.values()]
            self._throughput_chart.set_values(throughputs, "#48bb78")
            self._response_chart.set_values(response_times, "#4299e1")

            alert_count = self._dashboard.get_alert_count()
            overview_text = (
                f"系统活跃告警: {alert_count['active']}\n"
                f"  INFO: {alert_count['by_level'].get('info', 0)}  "
                f"WARNING: {alert_count['by_level'].get('warning', 0)}  "
                f"ERROR: {alert_count['by_level'].get('error', 0)}  "
                f"CRITICAL: {alert_count['by_level'].get('critical', 0)}\n"
                f"总运行次数: {summary['total_runs']}  |  整体稳定性: {summary['overall_stability']:.3f}"
            )
            self._overview_text.setText(overview_text)
        except Exception as e:
            self._overview_text.setText(f"获取数据失败: {e}")

    def _refresh_detectors(self) -> None:
        try:
            all_metrics = self._dashboard.get_all_metrics()
            filtered = [
                (name, m) for name, m in all_metrics.items()
                if not self._filter_text or self._filter_text in name.lower()
            ]

            sort_text = self._sort_combo.currentText()
            sort_keys = {
                "按名称": lambda x: x[0].lower(),
                "按状态": lambda x: x[1].get("status", ""),
                "按响应时间": lambda x: x[1].get("avg_response_time_ms", 0),
                "按成功率": lambda x: x[1].get("success_rate", 0),
                "按稳定性": lambda x: x[1].get("stability_index", 0),
            }
            key_func = sort_keys.get(sort_text, lambda x: x[0].lower())
            try:
                filtered.sort(key=key_func)
            except Exception:
                pass

            self._det_table.setRowCount(len(filtered))

            for row, (name, m) in enumerate(filtered):
                status_item = QTableWidgetItem("●")
                status_item.setForeground(QColor(STATUS_COLORS.get(m["status"], "#a0aec0")))
                status_item.setToolTip(m["status"])
                self._det_table.setItem(row, 0, status_item)

                self._det_table.setItem(row, 1, QTableWidgetItem(name))
                self._det_table.setItem(row, 2, QTableWidgetItem(str(m.get("priority", "-"))))
                self._det_table.setItem(row, 3, QTableWidgetItem(str(m["total_runs"])))
                self._det_table.setItem(row, 4, QTableWidgetItem(f"{m['success_rate']*100:.1f}%"))
                self._det_table.setItem(row, 5, QTableWidgetItem(f"{m['avg_response_time_ms']:.1f}"))
                self._det_table.setItem(row, 6, QTableWidgetItem(f"{m['detection_rate']*100:.1f}%"))
                self._det_table.setItem(row, 7, QTableWidgetItem(f"{m['false_positive_rate']*100:.1f}%"))
                self._det_table.setItem(row, 8, QTableWidgetItem(f"{m['stability_index']:.2f}"))

            if not getattr(self, "_det_col_widths_cached", False):
                self._det_table.resizeColumnsToContents()
                self._det_col_widths_cached = True
        except Exception:
            pass

    def _refresh_alerts(self) -> None:
        try:
            level_filter = self._alert_filter.currentText()
            alerts = self._dashboard.get_alerts(
                level=level_filter if level_filter != "全部" else None,
                limit=200,
            )
            self._alert_table.setRowCount(len(alerts))

            for row, alert in enumerate(alerts):
                level_item = QTableWidgetItem(alert["level"].upper())
                level_item.setForeground(QColor(ALERT_COLORS.get(alert["level"], "#a0aec0")))
                level_item.setData(Qt.ItemDataRole.UserRole, alert.get("alert_id", ""))
                self._alert_table.setItem(row, 0, level_item)
                self._alert_table.setItem(row, 1, QTableWidgetItem(alert["detector_name"]))
                self._alert_table.setItem(row, 2, QTableWidgetItem(alert["anomaly_type"]))
                self._alert_table.setItem(row, 3, QTableWidgetItem(alert["message"]))
                self._alert_table.setItem(row, 4, QTableWidgetItem(alert.get("created_at", "")))
                self._alert_table.setItem(row, 5, QTableWidgetItem("✓" if alert["acknowledged"] else ""))

            if not getattr(self, "_alert_col_widths_cached", False):
                self._alert_table.resizeColumnsToContents()
                self._alert_col_widths_cached = True
        except Exception:
            pass

    def _refresh_trend(self) -> None:
        try:
            detector_name = self._trend_detector.currentText()
            if not detector_name or self._trend_detector.count() == 0:
                if self._dashboard is None:
                    return
                all_metrics = self._dashboard.get_all_metrics()
                detector_names = list(all_metrics.keys())
                if not detector_names:
                    self._trend_text.setText("无可用检测器")
                    return
                current = self._trend_detector.currentText()
                self._trend_detector.blockSignals(True)
                self._trend_detector.clear()
                self._trend_detector.addItems(detector_names)
                if current in detector_names:
                    self._trend_detector.setCurrentText(current)
                self._trend_detector.blockSignals(False)
                detector_name = self._trend_detector.currentText()
                if not detector_name:
                    return

            time_range = self._trend_range.currentText()
            history = self._dashboard.get_history(detector_name, time_range=time_range)
            trend = self._dashboard.get_trend(detector_name)

            if history:
                response_times = [h.get("avg_response_time_ms", 0) for h in history]
                self._trend_chart.set_values(response_times, "#4299e1")

            rt = trend.get("response_time", {})
            sr = trend.get("success_rate", {})
            st = trend.get("stability", {})

            text = (
                f"检测器: {detector_name}\n"
                f"样本数: {trend.get('sample_count', 0)}\n\n"
                f"响应时间趋势: {rt.get('trend', '-')}  (变化率: {rt.get('relative_change', 0):.4f})\n"
                f"成功率趋势: {sr.get('trend', '-')}\n"
                f"稳定性: {st.get('trend', '-')}  (波动性: {st.get('volatility', 0):.4f})"
            )
            self._trend_text.setText(text)
        except Exception as e:
            self._trend_text.setText(f"趋势分析失败: {e}")

    def _on_detector_selected(self, index) -> None:
        try:
            row = index.row()
            name = self._det_table.item(row, 1).text()
            metrics = self._dashboard.get_detector_metrics(name)
            if metrics:
                detail = (
                    f"检测器: {name}  |  状态: {metrics['status']}  |  优先级: {metrics['priority']}\n"
                    f"运行: {metrics['total_runs']}次  |  成功: {metrics['successful_runs']}  |  失败: {metrics['failed_runs']}\n"
                    f"响应时间: 平均{metrics['avg_response_time_ms']}ms  最小{metrics['min_response_time_ms']}ms  最大{metrics['max_response_time_ms']}ms\n"
                    f"检测率: {metrics['detection_rate']*100:.1f}%  误报率: {metrics['false_positive_rate']*100:.1f}%  稳定性: {metrics['stability_index']:.2f}"
                )
                self._det_detail.setText(detail)
                self._trend_detector.setCurrentText(name)
        except Exception:
            pass

    def _apply_filter(self, text: str) -> None:
        self._filter_text = text.lower()
        self._refresh_detectors()

    def _on_sort_changed(self, index: int) -> None:
        self._refresh_detectors()

    def _acknowledge_selected(self) -> None:
        if self._dashboard is None:
            return
        seen_rows: set[int] = set()
        for item in self._alert_table.selectedItems():
            row = item.row()
            if row in seen_rows:
                continue
            seen_rows.add(row)
            alert_id = self._alert_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if alert_id:
                self._dashboard.acknowledge_alert(alert_id)
        self._refresh_alerts()

    def _resolve_selected(self) -> None:
        if self._dashboard is None:
            return
        seen_rows: set[int] = set()
        for item in self._alert_table.selectedItems():
            row = item.row()
            if row in seen_rows:
                continue
            seen_rows.add(row)
            alert_id = self._alert_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if alert_id:
                self._dashboard.resolve_alert(alert_id)
        self._refresh_alerts()

    def _save_thresholds(self) -> None:
        if self._dashboard is None:
            return
        thresholds = {
            "max_response_time_ms": self._spin_max_rt.value(),
            "min_success_rate": self._spin_min_success.value(),
            "max_false_positive_rate": self._spin_max_fp.value(),
            "max_idle_seconds": self._spin_max_idle.value(),
            "throughput_drop_ratio": self._spin_throughput_drop.value(),
            "accuracy_drop_ratio": self._spin_accuracy_drop.value(),
        }
        self._dashboard.set_thresholds(thresholds)


def show_dashboard_panel_pyqt(dashboard=None) -> DashboardPanelPyQt:
    """创建并显示仪表盘面板。"""
    panel = DashboardPanelPyQt()
    if dashboard:
        panel.set_dashboard(dashboard)
    return panel