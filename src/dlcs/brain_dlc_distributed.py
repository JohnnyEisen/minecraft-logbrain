"""Distributed DLC: 多 Worker 模拟与数据切分。

v2.1.0: 修复 shutdown 竞态条件——先发送毒丸再设置 is_running=False；
         修复结果队列写入异常时的静默丢失。
v2.0.0: DI 集成 (config/audit)，版本号统一引用 __version__。
"""
from __future__ import annotations

import logging
import threading
import queue
import time
from typing import Any, Dict, List, Optional
import math

from brain_system import BrainCore, BrainDLC, BrainDLCType, DLCManifest
from brain_system import __version__

class DistributedComputingDLC(BrainDLC):
    def get_manifest(self) -> DLCManifest:
        return DLCManifest(
            name="Distributed Computing",
            version=__version__,
            author="Brain AI Systems",
            description="提供简易的单机多Worker并行/数据切分能力",
            dlc_type=BrainDLCType.MANAGER,
            dependencies=["Brain Core", "Neural Workflow Manager"],
            priority=40
        )

    def _initialize(self):
        self.workers: List[threading.Thread] = []
        self.task_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.is_running = False
        logging.info("DistributedComputingDLC 初始化")

    def _pre_shutdown(self):
        self.stop_workers()

    def provide_computational_units(self) -> Dict[str, Any]:
        return {
            "start_workers": self.start_workers,
            "stop_workers": self.stop_workers,
            "parallel_map": self.parallel_map,
            "partition_data": self.partition_data,
        }

    def start_workers(self, num_workers: int = 2):
        if self.is_running:
            return
        
        self.is_running = True
        for i in range(num_workers):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()
            self.workers.append(t)
        logging.info(f"启动了 {num_workers} 个 Worker 线程")

    def stop_workers(self):
        """安全关闭所有 Worker 线程。

        先发送毒丸(None)通知 worker 退出，再设置 is_running=False 防止竞态。
        等待所有线程退出后清理列表。
        """
        if self.is_running:
            # 先发送毒丸，确保 worker 在 is_running=False 之前收到退出信号
            for _ in self.workers:
                self.task_queue.put(None)
        
        self.is_running = False
        
        for t in self.workers:
            if t.is_alive():
                t.join(timeout=2.0)
        self.workers.clear()

    def parallel_map(self, func, data_list: List[Any]) -> List[Any]:
        """类似 Pool.map 的并行执行。"""
        if not self.is_running:
            self.start_workers(2)

        total = len(data_list)
        results = [None] * total
        
        # 任务分发
        for idx, item in enumerate(data_list):
            self.task_queue.put((func, item, idx))

        # 收集结果，带超时保护
        completed = 0
        deadline = time.time() + max(len(data_list) * 30.0, 60.0)
        while completed < total:
            try:
                timeout = max(deadline - time.time(), 1.0)
                res = self.result_queue.get(timeout=timeout)
                if isinstance(res, Exception):
                    logging.error("Worker 异常: %s", res, exc_info=res if hasattr(res, '__traceback__') else False)
                else:
                    r_item, r_idx = res
                    results[r_idx] = r_item
                completed += 1
            except queue.Empty:
                logging.warning(
                    "并行任务超时: %d/%d 完成 (%d 丢失)",
                    completed, total, total - completed
                )
                break
        
        return results

    def partition_data(self, data: List[Any], num_partitions: int) -> List[List[Any]]:
        """简单的由 Host 执行的数据切分。"""
        chunk_size = math.ceil(len(data) / num_partitions)
        return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]

    def _worker_loop(self, worker_id: int):
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            if task is None: # Poison pill
                break
            
            func, item, idx = task
            try:
                res = func(item)
                self.result_queue.put((res, idx))
            except Exception as e:
                self.result_queue.put(e)
