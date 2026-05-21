import tkinter as tk
from tkinter import ttk
import sys

STATUS_COLORS = {
    "idle": "#95a5a6",
    "loading": "#3498db",
    "active": "#2ecc71",
    "warning": "#f39c12",
    "error": "#e74c3c",
}

class BrainMonitor:
    """简洁的 GPU 状态 + AI 分析状态指示器。"""

    def __init__(self, parent, root):
        self.parent = parent
        self.root = root
        self.status_var = tk.StringVar(value="AI: 未启用")

        self._create_widgets()

    def _create_widgets(self):
        container = ttk.Frame(self.parent)
        container.pack(side="right", padx=6)

        gpu_status_text, gpu_color = self._detect_gpu()

        gpu_frame = ttk.Frame(container)
        gpu_frame.pack(side="right", padx=5)

        ttk.Label(gpu_frame, text="GPU:", font=("Segoe UI", 7)).pack(side="left")
        ttk.Label(gpu_frame, text=gpu_status_text, foreground=gpu_color,
                   font=("Segoe UI", 9, "bold")).pack(side="left")

        try:
            style_bg = ttk.Style().lookup("TFrame", "background")
        except Exception:
            style_bg = "#f0f0f0"

        self.canvas = tk.Canvas(container, width=22, height=22, highlightthickness=0, bg=style_bg)
        self.canvas.pack(side="right", padx=4)
        self._draw_indicator(STATUS_COLORS["idle"])

    def _detect_gpu(self):
        try:
            import torch
            if torch.cuda.is_available():
                device = torch.cuda.get_device_name(0)
                return f"CUDA ({device})", "#27ae60"
            return "CPU (Torch)", "#f39c12"
        except ImportError:
            return "Standard", "#3498db"

    def _draw_indicator(self, color):
        self.canvas.delete("indicator")
        self.canvas.create_oval(3, 3, 19, 19, fill=color, outline="", tags="indicator")

    def set_status(self, text):
        self.status_var.set(text)
        if "失败" in text or "错误" in text:
            self._draw_indicator(STATUS_COLORS["error"])
        elif "Loading" in text or "初始化" in text or "启动" in text:
            self._draw_indicator(STATUS_COLORS["loading"])
        elif "完成" in text or "就绪" in text or "active" in text.lower() or "已启用" in text:
            self._draw_indicator(STATUS_COLORS["active"])
        elif "规则" in text or "降级" in text or "警告" in text:
            self._draw_indicator(STATUS_COLORS["warning"])
        else:
            self._draw_indicator(STATUS_COLORS["idle"])