"""
异常检测与告警机制。

检测检测器运行中的异常行为并生成告警。

模块说明:
    - AnomalyType: 异常类型枚举
    - AnomalyRecord: 异常记录
    - Alert: 告警对象
    - AlertLevel: 告警级别
    - AnomalyDetector: 基于历史指标的异常检测器
    - AlertManager: 告警管理器（阈值检查 + 通知）
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from mca_core.dashboard.metrics import DetectorMetrics, MetricThresholds


class AnomalyType(Enum):
    """异常类型。"""
    LONG_IDLE = "long_idle"
    THROUGHPUT_DROP = "throughput_drop"
    ACCURACY_DROP = "accuracy_drop"
    HIGH_RESPONSE_TIME = "high_response_time"
    HIGH_ERROR_RATE = "high_error_rate"
    HIGH_FALSE_POSITIVE = "high_false_positive"
    STATUS_CHANGE = "status_change"


class AlertLevel(Enum):
    """告警级别。"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AnomalyRecord:
    """异常记录。

    Attributes:
        detector_name: 检测器名称
        anomaly_type: 异常类型
        detected_at: 检测时间
        current_value: 当前值
        threshold: 阈值
        description: 描述
        severity: 严重程度
    """

    detector_name: str
    anomaly_type: AnomalyType
    detected_at: datetime = field(default_factory=datetime.now)
    current_value: float = 0.0
    threshold: float = 0.0
    description: str = ""
    severity: AlertLevel = AlertLevel.WARNING


@dataclass
class Alert:
    """告警对象。

    Attributes:
        alert_id: 告警唯一标识
        detector_name: 检测器名称
        level: 告警级别
        message: 告警消息
        anomaly_type: 异常类型
        created_at: 创建时间
        acknowledged: 是否已确认
        resolved_at: 解决时间
    """

    alert_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    detector_name: str = ""
    level: AlertLevel = AlertLevel.INFO
    message: str = ""
    anomaly_type: AnomalyType = AnomalyType.STATUS_CHANGE
    created_at: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False
    resolved_at: Optional[datetime] = None

    def resolve(self) -> None:
        self.resolved_at = datetime.now()

    def acknowledge(self) -> None:
        self.acknowledged = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "detector_name": self.detector_name,
            "level": self.level.value,
            "message": self.message,
            "anomaly_type": self.anomaly_type.value,
            "created_at": self.created_at.isoformat(),
            "acknowledged": self.acknowledged,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class AnomalyDetector:
    """基于历史指标的异常检测器。

    检测检测器运行中的异常行为模式:
        - 长时间无响应
        - 处理速度骤降
        - 准确率异常波动
        - 响应时间飙升
        - 错误率突增

    内置去重冷却：同一检测器+同一异常类型在冷却期内不重复生成。
    """

    COOLDOWN_SECONDS = 60.0

    def __init__(self) -> None:
        self._anomalies: List[AnomalyRecord] = []
        self._lock = threading.Lock()
        self._max_anomalies = 200
        self._last_alert_key: Dict[str, float] = {}

    def _make_key(self, detector_name: str, anomaly_type: AnomalyType) -> str:
        return f"{detector_name}:{anomaly_type.value}"

    def _is_cooled_down(self, key: str) -> bool:
        last = self._last_alert_key.get(key, 0.0)
        return (time.time() - last) >= self.COOLDOWN_SECONDS

    def detect(
        self,
        metrics: DetectorMetrics,
        thresholds: MetricThresholds,
        previous_metrics: Optional[DetectorMetrics] = None,
    ) -> List[AnomalyRecord]:
        """检测单个检测器的异常。

        Args:
            metrics: 当前指标
            thresholds: 告警阈值
            previous_metrics: 上一次的指标（用于趋势对比）

        Returns:
            异常记录列表
        """
        anomalies: List[AnomalyRecord] = []

        if metrics.last_run_at:
            idle_seconds = (datetime.now() - metrics.last_run_at).total_seconds()
            if idle_seconds > thresholds.max_idle_seconds:
                key = self._make_key(metrics.detector_name, AnomalyType.LONG_IDLE)
                if self._is_cooled_down(key):
                    anomalies.append(
                        AnomalyRecord(
                            detector_name=metrics.detector_name,
                            anomaly_type=AnomalyType.LONG_IDLE,
                            current_value=idle_seconds,
                            threshold=thresholds.max_idle_seconds,
                            description=f"检测器已空闲 {idle_seconds:.0f} 秒",
                            severity=AlertLevel.WARNING,
                        )
                    )
                    self._last_alert_key[key] = time.time()

        if metrics.avg_response_time_ms > thresholds.max_response_time_ms:
            key = self._make_key(metrics.detector_name, AnomalyType.HIGH_RESPONSE_TIME)
            if self._is_cooled_down(key):
                severity = (
                    AlertLevel.CRITICAL
                    if metrics.avg_response_time_ms > thresholds.max_response_time_ms * 3
                    else AlertLevel.ERROR
                    if metrics.avg_response_time_ms > thresholds.max_response_time_ms * 2
                    else AlertLevel.WARNING
                )
                anomalies.append(
                    AnomalyRecord(
                        detector_name=metrics.detector_name,
                        anomaly_type=AnomalyType.HIGH_RESPONSE_TIME,
                        current_value=metrics.avg_response_time_ms,
                        threshold=thresholds.max_response_time_ms,
                        description=f"平均响应时间 {metrics.avg_response_time_ms:.0f}ms 超过阈值 {thresholds.max_response_time_ms:.0f}ms",
                        severity=severity,
                    )
                )
                self._last_alert_key[key] = time.time()

        if metrics.total_runs > 10 and metrics.success_rate < thresholds.min_success_rate:
            key = self._make_key(metrics.detector_name, AnomalyType.HIGH_ERROR_RATE)
            if self._is_cooled_down(key):
                anomalies.append(
                    AnomalyRecord(
                        detector_name=metrics.detector_name,
                        anomaly_type=AnomalyType.HIGH_ERROR_RATE,
                        current_value=metrics.success_rate,
                        threshold=thresholds.min_success_rate,
                        description=f"成功率 {metrics.success_rate:.2%} 低于阈值 {thresholds.min_success_rate:.2%}",
                        severity=AlertLevel.ERROR,
                    )
                )
                self._last_alert_key[key] = time.time()

        if metrics.total_runs > 10 and metrics.false_positive_rate > thresholds.max_false_positive_rate:
            key = self._make_key(metrics.detector_name, AnomalyType.HIGH_FALSE_POSITIVE)
            if self._is_cooled_down(key):
                anomalies.append(
                    AnomalyRecord(
                        detector_name=metrics.detector_name,
                        anomaly_type=AnomalyType.HIGH_FALSE_POSITIVE,
                        current_value=metrics.false_positive_rate,
                        threshold=thresholds.max_false_positive_rate,
                        description=f"误报率 {metrics.false_positive_rate:.2%} 超过阈值 {thresholds.max_false_positive_rate:.2%}",
                        severity=AlertLevel.WARNING,
                    )
                )
                self._last_alert_key[key] = time.time()

        if previous_metrics and previous_metrics.total_runs > 0 and metrics.total_runs > 0:
            prev_throughput = previous_metrics.throughput_per_second
            curr_throughput = metrics.throughput_per_second
            if prev_throughput > 0 and curr_throughput / prev_throughput < (1.0 - thresholds.throughput_drop_ratio):
                key = self._make_key(metrics.detector_name, AnomalyType.THROUGHPUT_DROP)
                if self._is_cooled_down(key):
                    anomalies.append(
                        AnomalyRecord(
                            detector_name=metrics.detector_name,
                            anomaly_type=AnomalyType.THROUGHPUT_DROP,
                            current_value=curr_throughput,
                            threshold=prev_throughput * (1.0 - thresholds.throughput_drop_ratio),
                            description=f"吞吐量骤降: {prev_throughput:.1f} -> {curr_throughput:.1f}/s",
                            severity=AlertLevel.WARNING,
                        )
                    )
                    self._last_alert_key[key] = time.time()

            prev_accuracy = previous_metrics.detection_rate
            curr_accuracy = metrics.detection_rate
            if prev_accuracy > 0 and curr_accuracy / prev_accuracy < (1.0 - thresholds.accuracy_drop_ratio):
                key = self._make_key(metrics.detector_name, AnomalyType.ACCURACY_DROP)
                if self._is_cooled_down(key):
                    anomalies.append(
                        AnomalyRecord(
                            detector_name=metrics.detector_name,
                            anomaly_type=AnomalyType.ACCURACY_DROP,
                            current_value=curr_accuracy,
                            threshold=prev_accuracy * (1.0 - thresholds.accuracy_drop_ratio),
                            description=f"准确率骤降: {prev_accuracy:.2%} -> {curr_accuracy:.2%}",
                            severity=AlertLevel.ERROR,
                        )
                    )
                    self._last_alert_key[key] = time.time()

        with self._lock:
            self._anomalies.extend(anomalies)
            if len(self._anomalies) > self._max_anomalies:
                self._anomalies = self._anomalies[-self._max_anomalies:]

        return anomalies

    def get_anomalies(self, detector_name: Optional[str] = None) -> List[AnomalyRecord]:
        """获取异常记录。"""
        with self._lock:
            if detector_name:
                return [a for a in self._anomalies if a.detector_name == detector_name]
            return list(self._anomalies)

    def clear(self) -> None:
        with self._lock:
            self._anomalies.clear()


class AlertManager:
    """告警管理器。

    管理告警的创建、确认、解决和通知。
    支持可配置的通知回调。
    """

    def __init__(self, max_alerts: int = 500) -> None:
        self._alerts: List[Alert] = []
        self._lock = threading.Lock()
        self._max_alerts = max_alerts
        self._notify_callbacks: List[Callable[[Alert], None]] = []

    def add_notify_callback(self, callback: Callable[[Alert], None]) -> None:
        """添加告警通知回调。"""
        self._notify_callbacks.append(callback)

    def remove_notify_callback(self, callback: Callable[[Alert], None]) -> None:
        """移除告警通知回调。"""
        try:
            self._notify_callbacks.remove(callback)
        except ValueError:
            pass

    def create_alert(
        self,
        detector_name: str,
        anomaly_type: AnomalyType,
        level: AlertLevel,
        message: str,
    ) -> Alert:
        """创建告警。

        Args:
            detector_name: 检测器名称
            anomaly_type: 异常类型
            level: 告警级别
            message: 告警消息

        Returns:
            创建的告警对象
        """
        alert = Alert(
            detector_name=detector_name,
            level=level,
            message=message,
            anomaly_type=anomaly_type,
        )

        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > self._max_alerts:
                self._alerts = self._alerts[-self._max_alerts:]

        for callback in self._notify_callbacks:
            try:
                callback(alert)
            except Exception:
                pass

        return alert

    def create_from_anomaly(self, anomaly: AnomalyRecord) -> Alert:
        """从异常记录创建告警。"""
        return self.create_alert(
            detector_name=anomaly.detector_name,
            anomaly_type=anomaly.anomaly_type,
            level=anomaly.severity,
            message=anomaly.description,
        )

    def get_alerts(
        self,
        acknowledged: Optional[bool] = None,
        level: Optional[AlertLevel] = None,
        detector_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[Alert]:
        """查询告警。

        Args:
            acknowledged: 按确认状态筛选
            level: 按级别筛选
            detector_name: 按检测器筛选
            limit: 最大返回数量

        Returns:
            告警列表
        """
        with self._lock:
            result = list(self._alerts)
            if acknowledged is not None:
                result = [a for a in result if a.acknowledged == acknowledged]
            if level is not None:
                result = [a for a in result if a.level == level]
            if detector_name is not None:
                result = [a for a in result if a.detector_name == detector_name]
            return result[-limit:]

    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认告警。"""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.acknowledge()
                    return True
        return False

    def resolve_alert(self, alert_id: str) -> bool:
        """解决告警。"""
        with self._lock:
            for alert in self._alerts:
                if alert.alert_id == alert_id:
                    alert.resolve()
                    return True
        return False

    def get_active_count(self) -> int:
        """获取未解决的活跃告警数。"""
        with self._lock:
            return sum(1 for a in self._alerts if a.resolved_at is None)

    def get_count_by_level(self) -> Dict[str, int]:
        """按级别统计告警数。"""
        with self._lock:
            counts: Dict[str, int] = {level.value: 0 for level in AlertLevel}
            for alert in self._alerts:
                if alert.resolved_at is None:
                    counts[alert.level.value] += 1
            return counts

    def clear(self) -> None:
        """清除所有告警。"""
        with self._lock:
            self._alerts.clear()