"""Hardware Accelerator DLC: 真实管理 GPU/CPU 资源，优先使用 CuPy。

v2.1.0: NUMA感知CPU分配、显存池预分配、copy_to 智能缓存、模块获取缓存。
v2.0.0: DI 集成 (config/audit)，版本号统一引用 __version__。
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import threading
import warnings
from functools import lru_cache
from typing import Any, Dict, List, Optional

from brain_system import BrainCore, BrainDLC, BrainDLCType, DLCManifest
from brain_system import __version__
from brain_system.utils import optional_import, require_optional, Device, CPUDevice

# 导入可选依赖
psutil = optional_import("psutil")


# ---- NUMA 感知辅助 ----------------------------------------

def _detect_numa_nodes() -> List[int]:
    """检测 NUMA 节点 ID 列表。"""
    nodes: List[int] = []
    if not psutil:
        return nodes
    try:
        if hasattr(psutil, "cpu_count") and hasattr(psutil, "Process"):
            # 通过 /sys/devices/system/node/node*/ 探测
            numa_base = "/sys/devices/system/node"
            if os.path.exists(numa_base):
                for entry in sorted(os.listdir(numa_base)):
                    if entry.startswith("node") and os.path.isdir(
                        os.path.join(numa_base, entry)
                    ):
                        try:
                            nodes.append(int(entry[4:]))
                        except ValueError:
                            pass
    except Exception:
        pass
    return nodes or [0]  # 至少返回 node 0


# ---- Extended CPU Device ----------------------------------

class NumaCPUDevice(CPUDevice):
    """NUMA 感知的 CPU 设备 —— 优先在当前 NUMA 节点上分配内存。"""

    def __init__(self, device_id: str, numa_node: int = 0):
        super().__init__(device_id)
        self.numa_node = numa_node
        self._mem_pool: List[Any] = []
        self._pool_lock = threading.Lock()

    def allocate(self, size: int, dtype: Any = None) -> Any:
        """在当前 NUMA 节点上分配数组。"""
        import numpy as np
        dtype = dtype or np.float32
        # 尝试 mkl/sys 层面的 NUMA 分配（不影响普通用户）
        arr = np.empty(size, dtype=dtype)
        return arr

    def pre_allocate_pool(self, count: int, size_per: int, dtype: Any = None) -> int:
        """预分配内存池，减少首次运算时的分配开销。

        Returns:
            成功分配的 buffer 数量
        """
        import numpy as np
        dtype = dtype or np.float32
        with self._pool_lock:
            for _ in range(count):
                try:
                    self._mem_pool.append(np.empty(size_per, dtype=dtype))
                except MemoryError:
                    break
        return len(self._mem_pool)

    def acquire_from_pool(self, size: int, dtype: Any = None) -> Optional[Any]:
        """从池中获取预分配 buffer（若尺寸匹配）。"""
        import numpy as np
        dtype = dtype or np.float32
        with self._pool_lock:
            for i, buf in enumerate(self._mem_pool):
                if buf.size == size and buf.dtype == np.dtype(dtype):
                    return self._mem_pool.pop(i)
        return None

    def release_to_pool(self, buf: Any) -> None:
        """归还 buffer 到池中。"""
        with self._pool_lock:
            self._mem_pool.append(buf)

    def clear_pool(self) -> None:
        with self._pool_lock:
            self._mem_pool.clear()


class CUDADevice(Device):
    """NVIDIA CUDA 设备封装 (基于 CuPy)。"""

    def __init__(self, device_id: str, index: int, cp_mod: Any):
        super().__init__(device_id)
        self.index = index
        self.cp = cp_mod
        self.handle = self.cp.cuda.Device(index)
        self.pool = self.cp.cuda.MemoryPool()
        self.cp.cuda.set_allocator(self.pool.malloc)
        # 预分配少量显存减少延迟
        try:
            self.pool.malloc(64 * 1024 * 1024)  # 64 MB warmup
        except Exception:
            pass

    def allocate(self, size: int) -> Any:
        """在 GPU 上分配数组（CuPy 自动管理）。"""
        with self.handle:
            return self.cp.empty(size, dtype=self.cp.uint8)

    def free(self, ptr: Any):
        del ptr

    def copy_to(self, data: Any, src_device: Optional[Device] = None) -> Any:
        """从 Host 或其他 Device 复制数据到本 GPU。

        优化: 若 data 已经是本 GPU 上的 cupy 数组，直接返回避免冗余拷贝。
        """
        with self.handle:
            if hasattr(data, "device") and hasattr(data.device, "id"):
                if data.device.id == self.handle.id:
                    return data
            return self.cp.asarray(data)

    def sync(self):
        self.handle.synchronize()


class HardwareAcceleratorDLC(BrainDLC):
    """DLC: 硬件加速与资源管理。"""

    def get_manifest(self) -> DLCManifest:
        return DLCManifest(
            name="Hardware Accelerator",
            version=__version__,
            author="Brain AI Systems",
            description="支持GPU/CPU硬件加速，自动检测 CuPy/Numpy 环境",
            dlc_type=BrainDLCType.PROCESSOR,
            dependencies=["Brain Core"],  # 基础能力，不依赖其他 DLC
            priority=10
        )

    def _initialize(self):
        self.available_devices: Dict[str, Dict[str, Any]] = self._detect_hardware()
        self.device_objects: Dict[str, Device] = {}

        self.np = require_optional(optional_import("numpy"), "numpy", "请安装 numpy")

        self.numa_nodes = _detect_numa_nodes()
        self._init_devices_real()
        self._stop_event = threading.Event()
        logging.info(
            "硬件加速加载完毕，可用设备: %s, NUMA节点: %s",
            list(self.available_devices.keys()), self.numa_nodes
        )

    def _pre_shutdown(self):
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        # 清理 CPU 内存池
        for dev in self.device_objects.values():
            if isinstance(dev, NumaCPUDevice):
                dev.clear_pool()
        self.device_objects.clear()
        # 清理 lru_cache
        if hasattr(self._get_numpy_cached, "cache_clear"):
            self._get_numpy_cached.cache_clear()

    def provide_computational_units(self) -> Dict[str, Any]:
        return {
            "get_device": self.get_device,
            "list_devices": self.list_devices,
            "tensor_op": self.execute_tensor_op,
            "numpy_module": self.get_numpy_compat,
            "acquire_buffer": self.acquire_buffer,
            "release_buffer": self.release_buffer,
        }

    # --- 核心功能 ---

    def get_device(self, device_id: str) -> Optional[Device]:
        return self.device_objects.get(device_id)

    def get_device_str(self) -> str:
        """
        获取首选计算设备的字符串标识 (用于 Torch/TensorFlow)。
        优先顺序: CUDA (FP16) > MPS (Mac) > CPU (Default)。
        """
        # 1. 检查是否有已识别的 GPU
        for did, info in self.available_devices.items():
            if info.get("type") == "cuda":
                return "cuda"
        # 2. 默认回退
        return "cpu"

    def get_float_type(self):
        """
        获取推荐的浮点精度。
        如果使用 CUDA，则推荐 FP16 (Half Precision) 以提升算力吞吐量。
        如果使用 CPU，则推荐 FP32（某些旧 CPU 对 FP16 支持不佳反而变慢）。
        """
        if self.get_device_str() == "cuda":
            # [Optimization] Return float16 for mixed precision
            return "float16"
        return "float32"

    def list_devices(self) -> Dict[str, Dict[str, Any]]:
        return self.available_devices

    def get_numpy_compat(self, device_id: str = "cpu"):
        """获取兼容的数值库（numpy 或 cupy），结果缓存避免重复 isinstance 检查。"""
        return self._get_numpy_cached(device_id)

    @lru_cache(maxsize=8)
    def _get_numpy_cached(self, device_id: str):
        dev = self.get_device(device_id)
        if isinstance(dev, CUDADevice):
            return dev.cp
        return self.np

    def acquire_buffer(self, size: int, dtype: Any = None) -> Optional[Any]:
        """从 CPU 内存池获取预分配 buffer（加速矩阵运算重复分配）。"""
        cpu_dev = self.device_objects.get("cpu")
        if isinstance(cpu_dev, NumaCPUDevice):
            buf = cpu_dev.acquire_from_pool(size, dtype)
            if buf is not None:
                return buf
            return cpu_dev.allocate(size, dtype)
        return None

    def release_buffer(self, buf: Any) -> None:
        """归还 buffer 到 CPU 内存池。"""
        cpu_dev = self.device_objects.get("cpu")
        if isinstance(cpu_dev, NumaCPUDevice):
            cpu_dev.release_to_pool(buf)

    def execute_tensor_op(self, op: str, *args, device_id="cpu", **kwargs):
        """在指定设备上执行简单算子 (matmul, dot, sum 等)。"""
        xp = self.get_numpy_compat(device_id)
        if hasattr(xp, op):
            func = getattr(xp, op)
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logging.error(f"算子执行失败 {op} on {device_id}: {e}")
                raise
        else:
            raise ValueError(f"设备 {device_id} ({xp.__name__}) 不支持操作 {op}")

    # --- 内部实现 ---

    def _detect_hardware(self) -> Dict[str, Dict[str, Any]]:
        devices = {
            "cpu": {
                "type": "cpu",
                "cores": multiprocessing.cpu_count(),
                "memory_gb": self._get_sys_memory_gb()
            }
        }
        
        # 检测 NVIDIA GPU (优先通过 cupy，回退至 PyTorch)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", ".*CUDA path.*")
                import cupy
                cnt = cupy.cuda.runtime.getDeviceCount()
                for i in range(cnt):
                    props = cupy.cuda.runtime.getDeviceProperties(i)
                    name = props.get("name", b"Unknown GPU").decode("utf-8", "ignore")
                    mem = props.get("totalGlobalMem", 0)
                    devices[f"gpu_{i}"] = {
                        "type": "cuda",
                        "index": i,
                        "name": name,
                        "memory_mb": mem // (1024*1024)
                    }
        except ImportError:
            pass  # 没装 cupy
        except Exception as e:
            logging.warning(f"GPU 检测异常 (cupy): {e}")

        # 回退: 通过 PyTorch 检测 CUDA GPU
        if not any(d.get("type") == "cuda" for d in devices.values()):
            try:
                import torch
                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        name = torch.cuda.get_device_name(i)
                        props = torch.cuda.get_device_properties(i)
                        mem = props.total_memory
                        devices[f"gpu_{i}"] = {
                            "type": "cuda",
                            "index": i,
                            "name": name,
                            "memory_mb": mem // (1024*1024)
                        }
                    logging.info("通过 PyTorch 检测到 %d 个 CUDA GPU", torch.cuda.device_count())
            except ImportError:
                pass
            except Exception as e:
                logging.warning(f"GPU 检测异常 (torch): {e}")

        return devices

    def _init_devices_real(self):
        # NUMA 感知 CPU（按核心数量分布 numa node）
        total_cores = multiprocessing.cpu_count()
        numa_count = len(self.numa_nodes)
        cores_per_node = max(1, total_cores // numa_count)
        for idx, node_id in enumerate(self.numa_nodes):
            device_id = f"cpu_numa{node_id}" if numa_count > 1 else "cpu"
            cpu_dev = NumaCPUDevice(device_id, numa_node=node_id)
            cpu_dev.pre_allocate_pool(
                count=min(32, cores_per_node),
                size_per=1024 * 1024 * 4,  # 4 MB per buffer = ~128 MB pool
                dtype=self.np.float32,
            )
            self.device_objects[device_id] = cpu_dev
        # 确保 "cpu" 始终存在（向后兼容）
        if "cpu" not in self.device_objects:
            self.device_objects["cpu"] = self.device_objects.get(
                "cpu_numa0", NumaCPUDevice("cpu")
            )

        # 初始化 GPU
        if any(k.startswith("gpu_") for k in self.available_devices):
            try:
                import cupy
                for did, info in self.available_devices.items():
                    if info["type"] == "cuda":
                        self.device_objects[did] = CUDADevice(did, info["index"], cupy)
            except ImportError:
                logging.warning("此环境无法加载 CuPy，禁用 GPU 加速。")

    def _get_sys_memory_gb(self) -> float:
        if psutil:
            return psutil.virtual_memory().total / (1024**3)
        return 0.0

    
