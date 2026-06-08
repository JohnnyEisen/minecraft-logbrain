from __future__ import annotations

import re
from typing import List, Optional

from config.constants import CAUSE_OTHER
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class ModConflictsDetector(Detector):
    # FML CoreMod 警告模式
    _RE_FML_COREMOD = re.compile(
        r"(?:FMLCorePluginContainsFMLMod|coremod.*not signed|MCVersion annotation)",
        re.IGNORECASE
    )
    # 通用冲突关键词（排除版本冲突，由 VersionConflictDetector 处理）
    _RE_CONFLICT_LINE = re.compile(
        r"(?:failed to load mod|coremod.*conflict|mod.*loading.*error|"
        r"signature.*invalid|class.*loading.*error)",
        re.IGNORECASE
    )
    # 版本冲突关键词（由 VersionConflictDetector 处理，此处跳过）
    _RE_VERSION_CONFLICT = re.compile(
        r"(?:version\s+(?:conflict|mismatch|range|requirement)|"
        r"is\s+incompatible\s+with|incompatible\s+(?:mod\s+)?version|"
        r"requires\s+version|but\s+found\s+version|duplicate\s+mod)",
        re.IGNORECASE
    )

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        txt = crash_log or ""
        txt_lower = context.crash_log_lower
        found_any = False

        # 1. FML CoreMod 警告检测（高信号）
        fml_matches = self._RE_FML_COREMOD.findall(txt)
        if fml_matches:
            found_any = True
            context.add_result(
                "检测到 FML CoreMod 警告: 核心模组加载器存在配置或签名问题。",
                detector=self.get_name(),
                cause_label=CAUSE_OTHER,
            )
            for line in txt.splitlines():
                if self._RE_FML_COREMOD.search(line):
                    context.add_result(
                        f"  - {line.strip()[:300]}",
                        detector=self.get_name(),
                    )
            context.add_result(
                "Suggestion: 检查 coremod 是否与当前 Forge 版本兼容，确保所有 coremod 已签名。",
                detector=self.get_name(),
            )

        # 2. 通用冲突/不兼容关键词检测（排除版本冲突，由 VersionConflictDetector 处理）
        # 先检查是否有版本冲突，如果有则跳过通用冲突检测
        if not self._RE_VERSION_CONFLICT.search(txt):
            if "failed to load mod" in txt_lower or "loading error" in txt_lower or "coremod" in txt_lower:
                lines = []
                for line in txt.splitlines():
                    if self._RE_CONFLICT_LINE.search(line):
                        lines.append(line.strip()[:300])
                if lines:
                    found_any = True
                    context.add_result("日志中存在加载错误或不兼容提示（摘录）:", detector=self.get_name())
                    for l in lines[:10]:
                        context.add_result("  - " + l, detector=self.get_name())

        return context.results

    def get_name(self) -> str:
        return "ModConflictsDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_OTHER
