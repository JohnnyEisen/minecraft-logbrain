"""
检测器基类模块

定义统一的检测器接口，支持优先级排序和置信度评估。

类说明:
    - Detector: 检测器抽象基类，所有检测器必须继承此类
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from .contracts import AnalysisContext, DetectionResult

_RE_PACKAGE = re.compile(r'([a-z][a-z0-9_]*\.(?:[a-z][a-z0-9_]*\.)+[a-zA-Z0-9_]+)')

if TYPE_CHECKING:
    pass


class Detector(ABC):
    """检测器抽象基类。

    所有崩溃日志检测器必须继承此类，实现 |detect|_, |get_name|_, |get_cause_label|_。

    优先级排序（数值越低越先执行）:

    - ``PRIORITY_CRITICAL = 0`` — 致命级，最先执行
    - ``PRIORITY_HIGH = 10`` — 高优先级
    - ``PRIORITY_NORMAL = 50`` — 普通（默认）
    - ``PRIORITY_LOW = 100`` — 低优先级

    **用法**::

        class MyDetector(Detector):
            def get_name(self): return "My Detector"
            def get_cause_label(self): return "自定义原因"
            def detect(self, crash_log, context):
                if "pattern" in crash_log:
                    context.add_result(DetectionResult(
                        detector=self.get_name(),
                        message="检测到 pattern",
                        confidence=0.9,
                        cause_label=self.get_cause_label(),
                    ))
    """

    PRIORITY_CRITICAL: int = 0
    PRIORITY_HIGH: int = 10
    PRIORITY_NORMAL: int = 50
    PRIORITY_LOW: int = 100

    @abstractmethod
    def detect(
        self,
        crash_log: str,
        context: "AnalysisContext",
    ) -> List["DetectionResult"]:
        """对崩溃日志执行检测，结果写入 ``context``。

        :param crash_log: Minecraft 崩溃日志全文。
        :param context: ``AnalysisContext`` 实例，承载检测结果和元数据。
        :returns: ``DetectionResult`` 列表。
        """
        raise NotImplementedError

    @abstractmethod
    def get_name(self) -> str:
        """
        获取检测器的人类可读名称。
        
        Returns:
            检测器名称字符串
            
        Raises:
            NotImplementedError: 子类必须实现此方法
        """
        raise NotImplementedError

    @abstractmethod
    def get_cause_label(self) -> Optional[str]:
        """
        获取与此检测器关联的原因标签。
        
        用于在摘要中统计崩溃原因。
        
        Returns:
            原因标签字符串，如果没有关联标签则返回 None
            
        Raises:
            NotImplementedError: 子类必须实现此方法
        """
        raise NotImplementedError

    def get_priority(self) -> int:
        """
        获取检测优先级。
        
        较低的值会先执行。默认返回 PRIORITY_NORMAL。
        
        Returns:
            优先级整数值
        """
        return self.PRIORITY_NORMAL

    def get_confidence(self) -> float:
        """
        获取此检测器结果的默认置信度。
        
        Returns:
            置信度值，范围 0.0-1.0
        """
        return 0.8

    @staticmethod
    def extract_packages(text: str) -> List[str]:
        """
        从文本中提取可能是模组包名的字符串。
        
        Args:
            text: 待分析文本
            
        Returns:
            包名列表
        """
        return list(set(_RE_PACKAGE.findall(text)))
