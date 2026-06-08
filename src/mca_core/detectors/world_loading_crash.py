"""World Loading Crash Detector.

Detects crashes related to world loading, chunk corruption,
and dimension-related errors.
"""
from __future__ import annotations

import re
from typing import List, Optional

from config.constants import CAUSE_OTHER
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class WorldLoadingCrashDetector(Detector):
    """Detect world loading and chunk-related crashes."""

    _WORLD_PATTERNS = [
        re.compile(r"Exception loading blockstate", re.IGNORECASE),
        re.compile(r"Exception ticking world", re.IGNORECASE),
        re.compile(r"Error reading world", re.IGNORECASE),
        re.compile(r"Exception loading chunk", re.IGNORECASE),
        re.compile(r"Failed to load level", re.IGNORECASE),
        re.compile(r"Chunk.*corrupt", re.IGNORECASE),
    ]

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        txt = crash_log or ""

        matched = False
        for pattern in self._WORLD_PATTERNS:
            if pattern.search(txt):
                matched = True
                break

        if matched:
            context.add_result(
                "加载世界时发生错误，可能是区块损坏或模组实体数据异常。",
                detector=self.get_name(),
                cause_label=CAUSE_OTHER,
            )
            context.add_result(
                "Suggestion: 尝试使用NBTExplorer修复区块，或移除最近添加的维度/生物模组",
                detector=self.get_name(),
            )

        return context.results

    def get_name(self) -> str:
        return "WorldLoadingCrashDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_OTHER