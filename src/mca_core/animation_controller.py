import sys
import logging
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class StatusColors:
    GPU_AVAILABLE = "#27ae60"
    GPU_CPU = "#f39c12"
    GPU_STANDARD = "#3498db"
    GPU_ERROR = "#e74c3c"


class AnimationType(Enum):
    IDLE = "idle"
    LOADING = "loading"
    ACTIVE = "active"
    ERROR = "error"


_VALID_TRANSITIONS = {
    AnimationType.IDLE: {AnimationType.LOADING, AnimationType.ACTIVE, AnimationType.ERROR},
    AnimationType.LOADING: {AnimationType.IDLE, AnimationType.ACTIVE, AnimationType.ERROR},
    AnimationType.ACTIVE: {AnimationType.IDLE},
    AnimationType.ERROR: {AnimationType.IDLE},
}


class AnimationStateMachine:
    def __init__(self):
        self._state = AnimationType.IDLE
        self._frame = 0

    @property
    def state(self) -> AnimationType:
        return self._state

    @property
    def frame(self) -> int:
        return self._frame

    def tick(self) -> None:
        self._frame += 1

    def reset_frame(self) -> None:
        self._frame = 0

    def can_transition(self, to_state: AnimationType) -> bool:
        return to_state in _VALID_TRANSITIONS.get(self._state, set())

    def transition(self, to_state: AnimationType) -> bool:
        if not self.can_transition(to_state):
            return False
        self._state = to_state
        self.reset_frame()
        return True

    def set_error(self) -> bool:
        return self.transition(AnimationType.ERROR)

    def set_loading(self) -> bool:
        return self.transition(AnimationType.LOADING)

    def set_active(self) -> bool:
        return self.transition(AnimationType.ACTIVE)

    def set_idle(self) -> bool:
        return self.transition(AnimationType.IDLE)


def detect_gpu() -> dict:
    try:
        if "torch" in sys.modules:
            import torch
            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0)
                return {"status": f"CUDA ({device_name})", "color": StatusColors.GPU_AVAILABLE}
            return {"status": "CPU (PyTorch)", "color": StatusColors.GPU_CPU}
    except Exception:
        pass
    return {"status": "Standard", "color": StatusColors.GPU_STANDARD}


def map_status_to_animation_type(text: str) -> str:
    lower = text.lower()
    if any(kw in lower for kw in ["失败", "错误", "error", "异常", "崩溃"]):
        return "error"
    if any(kw in lower for kw in ["loading", "加载", "初始化", "启动"]):
        return "loading"
    if any(kw in lower for kw in ["完成", "就绪", "active", "运行", "已启用"]):
        return "active"
    if any(kw in lower for kw in ["规则", "降级", "警告", "warning", "degraded"]):
        return "warning"
    return "idle"