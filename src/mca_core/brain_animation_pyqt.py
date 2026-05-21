"""
PyQt6 大脑状态指示器 - Brain Status Indicator

简洁的状态指示组件，替代原花哨的解剖学大脑动画。
"""

import math
from typing import Optional

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen

from mca_core.animation_controller import (
    StatusColors,
    AnimationStateMachine,
    AnimationType,
    detect_gpu,
)

STATUS_COLORS = {
    "idle": "#95a5a6",
    "loading": "#3498db",
    "active": "#2ecc71",
    "warning": "#f39c12",
    "error": "#e74c3c",
}

class StatusIndicator(QWidget):
    """简洁的状态指示圆点，支持脉冲动画。"""

    def __init__(self, parent: Optional[QWidget] = None, size: int = 16):
        super().__init__(parent)
        self.setFixedSize(size + 8, size + 8)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._size = size
        self._animation_type = "idle"
        self._animation_frame = 0
        self._animation_timer: Optional[QTimer] = None

    def start_loading_animation(self) -> None:
        self._animation_type = "loading"
        self._animation_frame = 0
        self._start_timer(80)

    def start_active_animation(self) -> None:
        self._animation_type = "active"
        self._animation_frame = 0
        self._start_timer(80)

    def stop_animation(self) -> None:
        self._animation_type = "idle"
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None
        self.update()

    def set_error_state(self) -> None:
        self._animation_type = "error"
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None
        self.update()

    def _start_timer(self, interval_ms: int) -> None:
        if self._animation_timer:
            self._animation_timer.stop()
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._on_tick)
        self._animation_timer.start(interval_ms)

    def _on_tick(self) -> None:
        self._animation_frame += 1
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base_color = QColor(STATUS_COLORS.get(self._animation_type, STATUS_COLORS["idle"]))

        alpha = 255
        radius = self._size // 2
        if self._animation_type in ("loading", "active"):
            pulse = (math.sin(self._animation_frame * 0.3) + 1) / 2
            alpha = int(180 + 75 * pulse)
            radius = self._size // 2 + int(2 * pulse)

        cx = self.width() // 2
        cy = self.height() // 2

        painter.setBrush(QBrush(QColor(base_color.red(), base_color.green(), base_color.blue(), alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)


class BrainMonitorWidget(QFrame):
    """大脑监控组件 — 简洁版。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._gpu_label = QLabel("GPU:")
        self._gpu_label.setStyleSheet("font-size: 11px; color: #718096;")
        layout.addWidget(self._gpu_label)

        self._gpu_status_label = QLabel("检测中...")
        self._gpu_status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #95a5a6;")
        layout.addWidget(self._gpu_status_label)

        self._ai_status_label = QLabel("AI: 未启用")
        self._ai_status_label.setStyleSheet("font-size: 12px; color: #95a5a6; margin-left: 8px;")
        layout.addWidget(self._ai_status_label)

        self.status_indicator = StatusIndicator(self, size=14)
        layout.addWidget(self.status_indicator)
        layout.addStretch()

        self._detect_gpu_status()

    def _detect_gpu_status(self) -> None:
        result = detect_gpu()
        self._gpu_status_label.setText(result["status"])
        self._gpu_status_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {result['color']};"
        )

    _AI_STATE_LABELS: dict[str, str] = {
        "idle": "AI: 未启用",
        "loading": "AI: 加载中...",
        "active": "AI: 已就绪",
        "error": "AI: 初始化失败",
        "warning": "AI: 下载中..."
    }

    def set_ai_state(self, state: str) -> None:
        label_text = self._AI_STATE_LABELS.get(state, "AI: 未启用")
        self._ai_status_label.setText(label_text)

        if state == "error":
            self._ai_status_label.setStyleSheet("font-size: 12px; color: #e74c3c; margin-left: 6px;")
            self.status_indicator.set_error_state()
        elif state == "loading":
            self._ai_status_label.setStyleSheet("font-size: 12px; color: #3498db; margin-left: 6px;")
            self.status_indicator.start_loading_animation()
        elif state == "active":
            self._ai_status_label.setStyleSheet("font-size: 12px; color: #2ecc71; margin-left: 6px;")
            self.status_indicator.start_active_animation()
        elif state == "warning":
            self._ai_status_label.setStyleSheet("font-size: 12px; color: #f39c12; margin-left: 6px;")
            self.status_indicator.start_active_animation()
        else:
            self._ai_status_label.setStyleSheet("font-size: 12px; color: #95a5a6; margin-left: 6px;")
            self.status_indicator.stop_animation()

    def start_loading(self) -> None:
        self.status_indicator.start_loading_animation()

    def start_active(self) -> None:
        self.status_indicator.start_active_animation()

    def stop(self) -> None:
        self.status_indicator.stop_animation()