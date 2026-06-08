from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional


class DetectorCache:
    """检测器结果缓存（LRU + TTL 策略）。

    对同一日志哈希的检测结果进行缓存，避免对相同输入重复执行
    18 个检测器。LRU 按访问时间淘汰，TTL 按写入时间过期。

    属性:
        _cache: OrderedDict 实现 LRU 淘汰
        _lock: 线程安全锁
        _max_size: LRU 最大条目数
        _ttl_seconds: TTL 过期秒数（默认 600 = 10 分钟）
        _hits / _misses: 命中统计
    """

    def __init__(self, max_size: int = 128, ttl_seconds: float = 600.0) -> None:
        self._cache: OrderedDict[str, tuple[float, List[Dict[str, Any]]]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._hits: int = 0
        self._misses: int = 0

    @staticmethod
    def compute_log_hash(crash_log: str) -> str:
        prefix = crash_log[:65536] if len(crash_log) > 65536 else crash_log
        return hashlib.sha256(prefix.encode("utf-8")).hexdigest()

    def get(self, log_hash: str) -> Optional[List[Dict[str, Any]]]:
        with self._lock:
            if log_hash not in self._cache:
                self._misses += 1
                return None
            timestamp, results = self._cache[log_hash]
            if time.time() - timestamp > self._ttl_seconds:
                del self._cache[log_hash]
                self._misses += 1
                return None
            self._cache.move_to_end(log_hash)
            self._hits += 1
            return results

    def put(self, log_hash: str, results: List[Dict[str, Any]]) -> None:
        with self._lock:
            if log_hash in self._cache:
                self._cache.move_to_end(log_hash)
            self._cache[log_hash] = (time.time(), results)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0