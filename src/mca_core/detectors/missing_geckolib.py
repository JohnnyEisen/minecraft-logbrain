from __future__ import annotations

import re
from typing import List, Optional, ClassVar

from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class MissingGeckoLibDetector(Detector):
    _RE_GECKOLIB: ClassVar[re.Pattern[str]] = re.compile(
        r"software\.bernie\.geckolib", re.IGNORECASE
    )
    _RE_MOD_INSTANCE: ClassVar[re.Pattern[str]] = re.compile(
        r"Failed to create mod instance\.\s*ModID:\s*([A-Za-z0-9_\-]+)",
        re.IGNORECASE
    )

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        analyzer = context.analyzer
        analyzer.geckolib_missing_mods = []
        if not self._RE_GECKOLIB.search(crash_log or ""):
            return context.results
        ids = set()
        for m in self._RE_MOD_INSTANCE.finditer(crash_log):
            ids.add(m.group(1))
        if not ids:
            # 从 crash log 中提取与 GeckoLib 相关的实体类名
            for m in re.finditer(
                r"at\s+([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)"
                r"\.(?:<init>|<clinit>|\w+)\([^)]*\.java:\d+\)",
                crash_log, re.IGNORECASE
            ):
                pkg = m.group(1).lower()
                if "geckolib" in pkg:
                    continue
                parts = pkg.split(".")
                for part in parts:
                    if len(part) > 3 and part not in ("net", "com", "org", "software", "bernie", "core", "animatable", "controller", "model", "renderer", "entity", "client", "common", "server", "util", "utils", "api", "impl", "internal"):
                        ids.add(part)
                        break
        analyzer.geckolib_missing_mods = sorted(ids)
        return context.results

    def get_name(self) -> str:
        return "GeckoLibDetector"

    def get_cause_label(self) -> Optional[str]:
        return None
