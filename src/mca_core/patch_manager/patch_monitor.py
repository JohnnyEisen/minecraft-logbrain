from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class PatchMonitor:
    """补丁分发后台监控服务。

    独立线程运行，周期性采集补丁管理系统的运行指标：
        - 补丁数量变化趋势
        - 安装/失败率
        - 完整性状态
        - 异常告警

    可与仪表盘集成，提供实时监控数据。

    用法:
        monitor = PatchMonitor(patch_manager, interval=30.0)
        monitor.set_alert_callback(lambda evt: print(f"ALERT: {evt}"))
        monitor.start()
        # ...
        stats = monitor.get_stats()
        monitor.stop()
    """

    def __init__(self, patch_manager: Any, interval: float = 30.0) -> None:
        self._pm = patch_manager
        self._interval = max(5.0, interval)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._stats_callback: Optional[Callable[[Dict[str, Any]], None]] = None

        self._started_at: Optional[str] = None
        self._history: list[Dict[str, Any]] = []
        self._max_history = 720
        self._alert_history: list[Dict[str, Any]] = []
        self._max_alerts = 200

        self._last_state: dict[str, int] = {}
        self._verify_cycle = 0
        self._verify_interval = 20

    def set_alert_callback(self, cb: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        self._alert_callback = cb

    def set_stats_callback(self, cb: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        self._stats_callback = cb

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._started_at = datetime.now().isoformat()
        self._thread = threading.Thread(
            target=self._run,
            name="patch-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info("PatchMonitor 已启动 (间隔=%.1fs)", self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("PatchMonitor 已停止")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snapshot = self._collect()
                self._check_alerts(snapshot)
                self._record_history(snapshot)
                if self._stats_callback:
                    try:
                        self._stats_callback(snapshot)
                    except Exception:
                        pass
            except Exception as e:
                logger.error("PatchMonitor 采集异常: %s", e)
            self._stop_event.wait(self._interval)

    def _collect(self) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        try:
            summary = self._pm.get_state_summary()
            total = sum(summary.values())
            applied = summary.get("applied", 0)
            failed = summary.get("failed", 0)
            available = summary.get("available", 0)
            disabled = summary.get("disabled", 0)

            success_rate = 0.0
            if applied + failed > 0:
                success_rate = applied / (applied + failed)

            dirty_detectors = 0
            self._verify_cycle += 1
            if self._verify_cycle >= self._verify_interval:
                self._verify_cycle = 0
                try:
                    v_results = self._pm.verify_all()
                    dirty_detectors = sum(1 for ok, _ in v_results.values() if not ok)
                except Exception:
                    pass

            return {
                "timestamp": now,
                "total_patches": total,
                "applied": applied,
                "available": available,
                "failed": failed,
                "disabled": disabled,
                "success_rate": round(success_rate, 4),
                "integrity_failures": dirty_detectors,
                "monitor_uptime_seconds": self._uptime_seconds(),
            }
        except Exception as e:
            return {
                "timestamp": now,
                "error": str(e),
            }

    def _check_alerts(self, snapshot: Dict[str, Any]) -> None:
        alerts: list[Dict[str, Any]] = []

        if snapshot.get("error"):
            alerts.append({
                "type": "MONITOR_ERROR",
                "severity": "high",
                "message": f"监控采集异常: {snapshot['error']}",
                "timestamp": snapshot["timestamp"],
            })

        if snapshot.get("failed", 0) > 0:
            alerts.append({
                "type": "PATCH_FAILURE",
                "severity": "high",
                "message": f"{snapshot['failed']} 个补丁处于失败状态",
                "timestamp": snapshot["timestamp"],
            })

        if snapshot.get("integrity_failures", 0) > 0:
            alerts.append({
                "type": "INTEGRITY_FAILURE",
                "severity": "high",
                "message": f"{snapshot['integrity_failures']} 个补丁完整性校验失败",
                "timestamp": snapshot["timestamp"],
            })

        prev = self._last_state
        if prev and snapshot.get("total_patches", 0) < prev.get("total_patches", 0):
            alerts.append({
                "type": "PATCH_COUNT_DROP",
                "severity": "medium",
                "message": f"补丁数量减少: {prev['total_patches']} → {snapshot['total_patches']}",
                "timestamp": snapshot["timestamp"],
            })

        self._last_state = {
            "total_patches": snapshot.get("total_patches", 0),
            "applied": snapshot.get("applied", 0),
            "failed": snapshot.get("failed", 0),
        }

        for alert in alerts:
            self._alert_history.append(alert)
            if len(self._alert_history) > self._max_alerts:
                self._alert_history = self._alert_history[-self._max_alerts:]
            if self._alert_callback:
                try:
                    self._alert_callback(alert)
                except Exception:
                    pass

    def _record_history(self, snapshot: Dict[str, Any]) -> None:
        with self._lock:
            self._history.append(snapshot)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def _uptime_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.time() - datetime.fromisoformat(self._started_at).timestamp()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "latest": self._history[-1] if self._history else {},
                "history_count": len(self._history),
                "alert_count": len(self._alert_history),
                "uptime": self._uptime_seconds(),
                "is_running": self._thread is not None and self._thread.is_alive(),
            }

    def get_history(self, limit: int = 20) -> list[Dict[str, Any]]:
        with self._lock:
            return self._history[-limit:]

    def get_alerts(self, limit: int = 50) -> list[Dict[str, Any]]:
        return self._alert_history[-limit:]

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()