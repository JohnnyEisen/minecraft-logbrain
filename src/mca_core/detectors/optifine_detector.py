"""OptiFine Detector.

Detects OptiFine related issues: preview/unstable versions,
known incompatibilities with other rendering mods, and class transformer errors.
"""
from __future__ import annotations

import re
from typing import List, Optional

from config.constants import CAUSE_GPU
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class OptiFineDetector(Detector):
    """Detect OptiFine-specific issues and incompatibilities."""

    # OptiFine class transformer presence
    _RE_OPTIFINE_TRANSFORMER = re.compile(
        r"optifine\.(?:OptiFineClassTransformer|OptiFineTransformationService)",
        re.IGNORECASE
    )
    # General OptiFine mention in crash log (jar name, stack trace, etc.)
    _RE_OPTIFINE_LOG = re.compile(r"optifine", re.IGNORECASE)
    # OptiFine preview/unstable versions
    _RE_OPTIFINE_PREVIEW = re.compile(
        r"OptiFine_[\w._]*pre[\w._]*\.jar",
        re.IGNORECASE
    )
    # OptiFine version extraction
    _RE_OPTIFINE_VER = re.compile(
        r"OptiFine[_\s]+([\w._]+(?:pre[\w._]*)?)",
        re.IGNORECASE
    )
    # Known incompatible rendering mods (when OptiFine is present)
    _INCOMPATIBLE_RENDER_MODS = frozenset({
        "sodium", "iris", "rubidium", "embeddium", "oculus",
        "betterfps", "foamfix", "vintagium", "magnesium",
    })

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        txt = crash_log or ""
        analyzer = context.analyzer
        present_mods = {k.lower() for k in getattr(analyzer, "mods", {}).keys()}
        has_optifine = any("optifine" in m for m in present_mods)

        # 1. Check OptiFine presence in crash log (transformer, jar name, stack trace, etc.)
        transformer_match = self._RE_OPTIFINE_TRANSFORMER.search(txt)
        log_match = self._RE_OPTIFINE_LOG.search(txt)
        if transformer_match or log_match:
            has_optifine = True  # confirm from log even if not in mod list

        if not has_optifine:
            return context.results

        findings: list[str] = []

        # 2. Detect preview/unstable version
        preview_match = self._RE_OPTIFINE_PREVIEW.search(txt)
        if preview_match:
            findings.append(f"检测到 OptiFine 预览/测试版本: {preview_match.group(0)}")
        elif has_optifine:
            # Try to extract version from log
            ver_match = self._RE_OPTIFINE_VER.search(txt)
            if ver_match:
                optifine_ver = ver_match.group(1).strip()
                if "pre" in optifine_ver.lower():
                    findings.append(f"检测到 OptiFine 预览/不稳定版本: {optifine_ver}")

        # 3. Check incompatible render mods present alongside OptiFine
        conflict_mods = [
            m for m in present_mods
            if m != "optifine" and m in self._INCOMPATIBLE_RENDER_MODS
        ]
        if conflict_mods:
            findings.append(
                f"OptiFine 与以下渲染模组已知不兼容: {', '.join(sorted(conflict_mods))}"
            )

        # 4. Report if any findings
        if findings:
            context.add_result(
                "检测到 OptiFine 相关问题:",
                detector=self.get_name(),
                cause_label=CAUSE_GPU,
            )
            for finding in findings:
                context.add_result(f"  - {finding}", detector=self.get_name())
            context.add_result(
                "Suggestion: 考虑移除 OptiFine 并使用替代渲染优化模组 (Sodium/Rubidium + Oculus/Iris)。",
                detector=self.get_name(),
            )
        elif has_optifine:
            # OptiFine is present but no specific issues found — low signal info
            context.add_result(
                "检测到 OptiFine 已安装。OptiFine 作为核心模组修改渲染引擎，可能与部分模组冲突。",
                detector=self.get_name(),
                cause_label=CAUSE_GPU,
            )
            context.add_result(
                "Suggestion: 如果崩溃反复发生，建议临时移除 OptiFine 以排查是否为渲染相关冲突。",
                detector=self.get_name(),
            )

        return context.results

    def get_name(self) -> str:
        return "OptiFineDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_GPU