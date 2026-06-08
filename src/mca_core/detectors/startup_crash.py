"""Startup Crash Detector.

Detects game startup related crashes, e.g. initialization failures,
launch errors, main thread exceptions, and missing mod exceptions.
"""
from __future__ import annotations

import re
from typing import List, Optional

from config.constants import CAUSE_OTHER, CAUSE_DEP
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class StartupCrashDetector(Detector):
    """Detect game startup failures."""

    _STARTUP_PATTERNS = [
        re.compile(r"Initialization failed", re.IGNORECASE),
        re.compile(r"Unable to launch", re.IGNORECASE),
        re.compile(r'Exception in thread "main"', re.IGNORECASE),
        re.compile(r"Could not create the (?:Minecraft|Game) window", re.IGNORECASE),
        re.compile(r"Failed to start the game", re.IGNORECASE),
    ]

    # MissingModsException — 最常见的 Minecraft 崩溃类型
    _RE_MISSING_MODS_EXCEPTION = re.compile(r"MissingModsException", re.IGNORECASE)

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        txt = crash_log or ""

        # 优先检测 MissingModsException（最常见的崩溃类型）
        if self._RE_MISSING_MODS_EXCEPTION.search(txt):
            context.add_result(
                "检测到 MissingModsException: 核心模组缺失导致游戏无法启动。",
                detector=self.get_name(),
                cause_label=CAUSE_DEP,
            )
            context.add_result(
                "Suggestion: 检查是否安装了所有前置模组，查看上方缺失依赖列表。",
                detector=self.get_name(),
            )
            return context.results

        matched = False
        for pattern in self._STARTUP_PATTERNS:
            if pattern.search(txt):
                matched = True
                break

        if matched:
            context.add_result(
                "游戏启动失败，通常是核心库缺失或版本不匹配。",
                detector=self.get_name(),
                cause_label=CAUSE_OTHER,
            )
            context.add_result(
                "Suggestion: 检查Java版本是否符合游戏要求，验证游戏核心文件完整性",
                detector=self.get_name(),
            )

        return context.results

    def get_name(self) -> str:
        return "StartupCrashDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_OTHER