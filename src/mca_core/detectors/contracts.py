"""
检测器契约模块

定义检测器和分析上下文的数据结构。

类说明:
    - DetectionResult: 单个检测结果数据类（含置信度评分）
    - AnalysisContext: 分析上下文，管理检测过程状态

版本: 2.0 — 新增置信度评分、跳过提示、进度回调、结果去重
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set

if TYPE_CHECKING:
    from threading import RLock


@dataclass
class DetectionResult:
    message: str
    detector: str
    cause_label: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.message[:120], self.detector))


@dataclass
class AnalysisContext:
    analyzer: Any
    crash_log: str
    results: List[DetectionResult] = field(default_factory=list)
    cause_counts: Dict[str, int] = field(default_factory=dict)
    crash_log_lower: str = field(default="", init=False, repr=False)

    _seen_messages: Set[str] = field(default_factory=set, repr=False)
    _skip_detectors: Set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self.crash_log_lower = (self.crash_log or "").lower()

    def skip_detector(self, name: str) -> None:
        self._skip_detectors.add(name)

    def is_skipped(self, name: str) -> bool:
        return name in self._skip_detectors

    def _add_result_internal(
        self,
        message: str,
        detector: str,
        cause_label: Optional[str],
        metadata: Dict[str, Any],
        confidence: float = 1.0,
    ) -> DetectionResult:
        msg_key = f"{detector}:{message[:120]}"
        if msg_key in self._seen_messages:
            return DetectionResult(message="", detector="", confidence=0.0)
        self._seen_messages.add(msg_key)

        if self.analyzer and message:
            self.analyzer.analysis_results.append(f"[{detector}] {message}")
            if hasattr(self.analyzer, "_auto_test_write_log"):
                try:
                    self.analyzer._auto_test_write_log(
                        f"DEBUG: add_result matches: {detector} -> {cause_label}"
                    )
                except Exception:
                    pass

        if self.analyzer and cause_label:
            try:
                if hasattr(self.analyzer, "add_cause"):
                    self.analyzer.add_cause(cause_label)
                elif hasattr(self.analyzer, "_add_cause"):
                    self.analyzer._add_cause(cause_label)
            except Exception:
                pass

        if cause_label:
            self.cause_counts[cause_label] = self.cause_counts.get(cause_label, 0) + 1

        res = DetectionResult(
            message=message,
            detector=detector,
            cause_label=cause_label,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.results.append(res)
        return res

    def add_result(
        self,
        message: str,
        detector: str,
        cause_label: Optional[str] = None,
        confidence: float = 1.0,
        **metadata: Any,
    ) -> DetectionResult:
        lock: Optional[RLock] = getattr(self.analyzer, "lock", None)
        if lock:
            with lock:
                return self._add_result_internal(
                    message, detector, cause_label, metadata or {}, confidence
                )
        else:
            return self._add_result_internal(
                message, detector, cause_label, metadata or {}, confidence
            )

    def add_result_block(
        self,
        header: str,
        items: List[str],
        detector: str,
        cause_label: Optional[str] = None,
        confidence: float = 1.0,
    ) -> None:
        lock: Optional[RLock] = getattr(self.analyzer, "lock", None)

        def _do_work() -> None:
            self._add_result_internal(header, detector, cause_label, {}, confidence)
            for item in items:
                self._add_result_internal(item, detector, None, {})

        if lock:
            with lock:
                _do_work()
        else:
            _do_work()