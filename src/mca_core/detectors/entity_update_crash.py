"""Entity Update Crash Detector.

Detects crashes caused by entity ticking/update logic errors.
"""
from __future__ import annotations

import re
from typing import List, Optional

from config.constants import CAUSE_OTHER
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class EntityUpdateCrashDetector(Detector):
    """Detect entity ticking and update-related crashes."""

    _ENTITY_PATTERNS = [
        re.compile(r"Ticking entity", re.IGNORECASE),
        re.compile(r"Entity being ticked", re.IGNORECASE),
        re.compile(r"Ticking block entity", re.IGNORECASE),
        re.compile(r"Exception.*entity.*update", re.IGNORECASE),
        re.compile(r"Entity.*tick.*error", re.IGNORECASE),
    ]

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        txt = crash_log or ""

        matched = False
        for pattern in self._ENTITY_PATTERNS:
            if pattern.search(txt):
                matched = True
                break

        if matched:
            context.add_result(
                "实体更新逻辑错误，通常由特定生物或物品引起。",
                detector=self.get_name(),
                cause_label=CAUSE_OTHER,
            )
            context.add_result(
                "Suggestion: 使用命令 /kill @e[type=...] 清除报错实体，或移除相关模组",
                detector=self.get_name(),
            )

        return context.results

    def get_name(self) -> str:
        return "EntityUpdateCrashDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_OTHER