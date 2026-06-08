"""
统一评分模块

提供崩溃原因的评分抽象层，统一分散在 AutoTestService 和 CrashPatternLearner
中的评分逻辑，确保评分标准的一致性。

使用方式:
    scorer = CrashCauseScorer()
    scores = scorer.score(crash_log_text)
    # scores: {"内存溢出": 0.8, "缺失依赖": 0.5, ...}
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from config.constants import (
    CAUSE_MEM,
    CAUSE_DEP,
    CAUSE_VER,
    CAUSE_DUP,
    CAUSE_GPU,
    CAUSE_GECKO,
    CAUSE_OTHER,
)


class CrashCauseScorer:
    """统一的崩溃原因评分器。

    封装了崩溃原因的关键词匹配和正则模式匹配逻辑，
    为 AutoTestService 和 CrashPatternLearner 提供一致的评分标准。
    """

    # 评分规则: (cause_label, keywords, [patterns])
    _RULES: List[Tuple[str, List[str], List[re.Pattern]]] = [
        (
            CAUSE_MEM,
            ["outofmemory", "内存", "heap", "oom"],
            [
                re.compile(r"out of memory|oom|heap space", re.IGNORECASE),
                re.compile(r"OutOfMemoryError", re.IGNORECASE),
            ],
        ),
        (
            CAUSE_DEP,
            ["missing mod", "missing or unsupported", "依赖", "requires", "缺失"],
            [
                re.compile(r"missing (?:mod|dependency|requirement)", re.IGNORECASE),
                re.compile(r"Missing or unsupported mandatory dependencies", re.IGNORECASE),
            ],
        ),
        (
            CAUSE_VER,
            ["版本", "version", "incompatible"],
            [
                re.compile(r"version conflict", re.IGNORECASE),
                re.compile(r"incompatible (?:mod|version)", re.IGNORECASE),
            ],
        ),
        (
            CAUSE_GPU,
            ["opengl", "glfw", "gl ", "渲染"],
            [
                re.compile(r"opengl (?:error|invalid)", re.IGNORECASE),
                re.compile(r"glfw error", re.IGNORECASE),
            ],
        ),
        (
            CAUSE_GECKO,
            ["geckolib", "geckoanimatable"],
            [
                re.compile(r"geckolib", re.IGNORECASE),
                re.compile(r"NoClassDefFoundError.*geckolib", re.IGNORECASE),
            ],
        ),
        (
            CAUSE_DUP,
            ["duplicate mod", "重复", "found in both"],
            [
                re.compile(r"duplicate mod", re.IGNORECASE),
                re.compile(r"found in both.*\.jar", re.IGNORECASE),
            ],
        ),
        (
            CAUSE_OTHER,
            ["mixin", "混入", "conflict"],
            [
                re.compile(r"mixin (?:apply|error|conflict|injection)", re.IGNORECASE),
                re.compile(r"MixinTransformerError", re.IGNORECASE),
            ],
        ),
    ]

    def score(self, crash_log: str) -> Dict[str, float]:
        """对崩溃日志进行评分。

        Args:
            crash_log: 崩溃日志文本

        Returns:
            {cause_label: score} 字典，score 范围 0.0-1.0
        """
        if not crash_log:
            return {}

        log_lower = crash_log.lower()
        scores: Dict[str, float] = {}

        for cause_label, keywords, patterns in self._RULES:
            match_count = 0

            for kw in keywords:
                if kw in log_lower:
                    match_count += 1

            for pattern in patterns:
                if pattern.search(crash_log):
                    match_count += 1

            if match_count > 0:
                scores[cause_label] = min(match_count * 0.3, 1.0)

        return scores

    def has_cause(self, crash_log: str, cause_label: str) -> bool:
        """检查崩溃日志是否包含指定崩溃原因。

        Args:
            crash_log: 崩溃日志文本
            cause_label: 崩溃原因标签（如 CAUSE_MEM）

        Returns:
            是否匹配
        """
        scores = self.score(crash_log)
        return cause_label in scores

    def get_matching_causes(self, crash_log: str) -> List[str]:
        """获取匹配的崩溃原因标签列表。

        Args:
            crash_log: 崩溃日志文本

        Returns:
            匹配的崩溃原因标签列表
        """
        return list(self.score(crash_log).keys())

    def get_top_causes(self, crash_log: str, top_n: int = 3) -> List[Tuple[str, float]]:
        """获取评分最高的 N 个崩溃原因。

        Args:
            crash_log: 崩溃日志文本
            top_n: 返回数量

        Returns:
            [(cause_label, score), ...] 按分数降序排列
        """
        scores = self.score(crash_log)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]

    def get_error_keywords(self) -> List[str]:
        """获取所有错误关键词，用于正常场景误报检测。

        Returns:
            所有错误关键词的列表
        """
        keywords: set[str] = set()
        for _, kws, _ in self._RULES:
            keywords.update(kws)
        # 添加额外的通用错误关键词
        keywords.update(["错误", "崩溃"])
        return list(keywords)