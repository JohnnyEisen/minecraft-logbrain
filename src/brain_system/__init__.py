"""brain_system: 简洁可扩展的大脑核心 + DLC 框架。

这个包负责：
- 核心 BrainCore（任务调度、缓存、DLC 注册、可选监控）
- DLC 基类 BrainDLC
- 类型定义（DLCManifest / BrainDLCType）

顶层脚本（如 Bain.py）只负责：定义 DLC 实现与演示入口。
"""

__all__ = [
    "BrainDLCType",
    "DLCManifest",
    "BrainDLC",
    "BrainCore",
]

__lazy_imports: dict[str, object] = {}


def __getattr__(name: str) -> object:
    if name in __lazy_imports:
        return __lazy_imports[name]

    if name in ("BrainDLCType", "DLCManifest"):
        from .models import BrainDLCType, DLCManifest
        __lazy_imports["BrainDLCType"] = BrainDLCType
        __lazy_imports["DLCManifest"] = DLCManifest
        return __lazy_imports[name]

    if name == "BrainDLC":
        from .dlc import BrainDLC
        __lazy_imports["BrainDLC"] = BrainDLC
        return BrainDLC

    if name == "BrainCore":
        from .core import BrainCore
        __lazy_imports["BrainCore"] = BrainCore
        return BrainCore

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")