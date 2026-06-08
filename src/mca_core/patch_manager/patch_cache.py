from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional


class PatchCache:
    """补丁扫描缓存（mtime 失效策略）。

    避免每次 scan() 都重新读取磁盘。通过文件修改时间 (mtime)
    判断缓存是否仍有效。

    属性:
        _cache: LRU 有序字典 (max 200 条目)
        _lock: 线程安全锁
    """

    def __init__(self, max_size: int = 200) -> None:
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        self._hits: int = 0
        self._misses: int = 0

    def get_meta(self, file_path: str) -> Optional[tuple[float, Any]]:
        """获取缓存的元数据，检查 mtime 是否过期。

        Returns:
            (cached_at, data) 或 None（未命中/过期）
        """
        with self._lock:
            if file_path not in self._cache:
                self._misses += 1
                return None

            cached_at, data = self._cache[file_path]
            try:
                current_mtime = os.path.getmtime(file_path)
                if int(current_mtime) > int(cached_at):
                    del self._cache[file_path]
                    self._misses += 1
                    return None
            except OSError:
                del self._cache[file_path]
                self._misses += 1
                return None

            self._cache.move_to_end(file_path)
            self._hits += 1
            return cached_at, data

    def put_meta(self, file_path: str, data: Any) -> None:
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            mtime = time.time()

        with self._lock:
            if file_path in self._cache:
                self._cache.move_to_end(file_path)
            self._cache[file_path] = (mtime, data)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def get_state(self, state_file: str) -> Optional[tuple[float, Any]]:
        return self.get_meta(state_file)

    def put_state(self, state_file: str, data: dict[str, Any]) -> None:
        self.put_meta(state_file, data)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def invalidate(self, file_path: str) -> None:
        with self._lock:
            self._cache.pop(file_path, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0