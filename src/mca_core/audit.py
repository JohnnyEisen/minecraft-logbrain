"""
审计追踪模块 — Audit Trail

提供全系统操作审计与变更记录能力，包括：
    - 操作日志：记录每次关键操作的 who/when/what/result
    - 变更追踪：追踪配置、补丁、DLC 等实体变更
    - 版本回溯：保存变更快照，支持回滚到历史版本

设计原则：
    - 不可变记录：AuditEntry 和 ChangeRecord 创建后不可修改
    - 线程安全：所有写入操作通过 threading.Lock 串行化
    - 内存上限：审计日志有 max_entries 限制，超出时 FIFO 淘汰
    - 轻量级：对性能影响最小化，适用于高并发场景

分层位置：
    位于基础设施层，被 AppBootstrap 创建，注入到所有需要审计的组件。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class OperationType(Enum):
    """操作类型枚举 — 覆盖全系统关键操作。"""

    # 系统级
    SYSTEM_START = "system.start"
    SYSTEM_STOP = "system.stop"
    SYSTEM_RESTART = "system.restart"

    # 配置变更
    CONFIG_CHANGE = "config.change"
    CONFIG_SAVE = "config.save"
    CONFIG_LOAD = "config.load"
    CONFIG_RESET = "config.reset"

    # 检测器
    DETECTOR_RUN = "detector.run"
    DETECTOR_REGISTER = "detector.register"
    DETECTOR_RESULT = "detector.result"

    # 补丁
    PATCH_INSTALL = "patch.install"
    PATCH_REMOVE = "patch.remove"
    PATCH_ROLLBACK = "patch.rollback"
    PATCH_VERIFY = "patch.verify"
    PATCH_SCAN = "patch.scan"

    # DLC
    DLC_LOAD = "dlc.load"
    DLC_UNLOAD = "dlc.unload"
    DLC_HOTLOAD = "dlc.hotload"

    # 插件
    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_UNLOADED = "plugin.unloaded"

    # 诊断
    DIAGNOSTIC_COMPLETE = "diagnostic.complete"
    DIAGNOSTIC_ERROR = "diagnostic.error"

    # 异常/告警
    ANOMALY_DETECTED = "anomaly.detected"
    ALERT_CREATED = "alert.created"
    ALERT_ACKNOWLEDGED = "alert.acknowledged"
    ALERT_RESOLVED = "alert.resolved"

    # 错误
    ERROR = "error.unexpected"

    # 通用
    CUSTOM = "custom"


@dataclass(frozen=True)
class AuditEntry:
    """审计日志条目 — 不可变记录。

    Attributes:
        entry_id: 唯一标识
        timestamp: 操作时间
        op_type: 操作类型
        component: 发起组件名
        detail: 操作描述
        metadata: 附加元数据
        success: 是否成功
        user_id: 操作者标识（可选）
    """

    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: datetime = field(default_factory=datetime.now)
    op_type: OperationType = OperationType.CUSTOM
    component: str = "unknown"
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    user_id: str = "system"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "type": self.op_type.value,
            "component": self.component,
            "detail": self.detail,
            "metadata": self.metadata,
            "success": self.success,
            "user_id": self.user_id,
        }


@dataclass(frozen=True)
class ChangeRecord:
    """变更记录 — 追踪某实体从 A 版本到 B 版本的变更。

    Attributes:
        change_id: 唯一标识
        entity_type: 实体类型（如 "config", "patch", "dlc"）
        entity_id: 实体唯一标识
        old_value: 变更前的值（序列化为可比较格式）
        new_value: 变更后的值
        timestamp: 变更时间
        component: 发起变更的组件
        reason: 变更原因
    """

    change_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    entity_type: str = ""
    entity_id: str = ""
    old_value: Any = None
    new_value: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    component: str = "unknown"
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "change_id": self.change_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "timestamp": self.timestamp.isoformat(),
            "component": self.component,
            "reason": self.reason,
        }


class AuditTrail:
    """审计追踪管理器。

    提供操作日志和变更记录的双轨追踪：
        - 操作日志流（entries）：记录所有操作事件
        - 变更历史流（changes）：记录实体版本变更

    线程安全，支持回调通知。

    使用示例:
        >>> audit = AuditTrail(max_entries=1000)
        >>> audit.record(OperationType.CONFIG_CHANGE, "修改UI主题", component="settings")
        >>> audit.record_change("config", "app.theme", "light", "dark", component="settings")
        >>> print(audit.count())
        2
    """

    def __init__(self, max_entries: int = 2000, max_changes: int = 1000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries 必须 >= 1")
        if max_changes < 1:
            raise ValueError("max_changes 必须 >= 1")

        self._entries: List[AuditEntry] = []
        self._changes: Dict[str, List[ChangeRecord]] = {}
        self._max_entries = max_entries
        self._max_changes = max_changes
        self._lock = threading.Lock()
        self._listeners: List = []

    def record(
        self,
        op_type: OperationType,
        detail: str = "",
        *,
        component: str = "unknown",
        metadata: Optional[Dict[str, Any]] = None,
        success: bool = True,
        user_id: str = "system",
        trigger_callback: bool = True,
    ) -> AuditEntry:
        """记录操作日志。"""
        entry = AuditEntry(
            op_type=op_type,
            component=component,
            detail=detail,
            metadata=metadata or {},
            success=success,
            user_id=user_id,
        )

        with self._lock:
            self._entries.append(entry)
            while len(self._entries) > self._max_entries:
                self._entries.pop(0)

        if trigger_callback:
            self._notify_listeners(entry)

        return entry

    def record_change(
        self,
        entity_type: str,
        entity_id: str,
        old_value: Any,
        new_value: Any,
        *,
        component: str = "unknown",
        reason: str = "",
    ) -> ChangeRecord:
        """记录实体变更（用于版本回溯）。"""
        record = ChangeRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            component=component,
            reason=reason,
        )

        key = f"{entity_type}:{entity_id}"
        with self._lock:
            changes = self._changes.setdefault(key, [])
            changes.append(record)
            while len(changes) > self._max_changes:
                changes.pop(0)

        return record

    def get_changes(
        self, entity_type: str, entity_id: str
    ) -> List[ChangeRecord]:
        """获取指定实体的变更历史。"""
        key = f"{entity_type}:{entity_id}"
        with self._lock:
            return list(self._changes.get(key, []))

    def get_entries(
        self,
        op_type: Optional[OperationType] = None,
        component: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """查询审计日志（按类型和组件过滤）。"""
        with self._lock:
            entries = list(self._entries)

        if op_type is not None:
            entries = [e for e in entries if e.op_type == op_type]
        if component is not None:
            entries = [e for e in entries if e.component == component]

        return entries[-limit:]

    def get_recent(
        self, limit: int = 50
    ) -> List[AuditEntry]:
        """获取最近的审计日志。"""
        with self._lock:
            return list(self._entries[-limit:])

    def get_all_entries(self) -> List[AuditEntry]:
        """获取所有审计日志。"""
        with self._lock:
            return list(self._entries)

    def count(self) -> int:
        """返回审计日志条目数。"""
        with self._lock:
            return len(self._entries)

    def change_count(self) -> int:
        """返回变更记录总数。"""
        with self._lock:
            return sum(len(v) for v in self._changes.values())

    def clear(self) -> None:
        """清空所有审计记录。"""
        with self._lock:
            self._entries.clear()
            self._changes.clear()

    def add_listener(self, callback) -> None:
        """注册审计监听器。

        每次记录操作日志时，监听器将被异步调用。
        监听器接收 AuditEntry 参数，不应抛出异常。
        """
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        """移除审计监听器。"""
        with self._lock:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

    def _notify_listeners(self, entry: AuditEntry) -> None:
        """通知监听器（异常隔离）。"""
        listeners = []
        with self._lock:
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(entry)
            except Exception:
                pass

    def export_entries(self) -> List[Dict[str, Any]]:
        """导出全部审计日志为字典列表。"""
        with self._lock:
            return [e.to_dict() for e in self._entries]

    def export_changes(
        self, entity_type: Optional[str] = None, entity_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """导出变更记录为字典列表。"""
        with self._lock:
            result: List[Dict[str, Any]] = []
            for key, changes in self._changes.items():
                et, eid = key.split(":", 1)
                if entity_type is not None and et != entity_type:
                    continue
                if entity_id is not None and eid != entity_id:
                    continue
                result.extend(c.to_dict() for c in changes)
            return result

    def __len__(self) -> int:
        return self.count()