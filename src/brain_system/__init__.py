"""brain_system: 简洁可扩展的大脑核心 + DLC 框架。

这个包负责：
- 核心 BrainCore（任务调度、缓存、DLC 注册、可选监控）
- DLC 基类 BrainDLC
- 类型定义（DLCManifest / BrainDLCType）

顶层脚本（如 Bain.py）只负责：定义 DLC 实现与演示入口。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import BrainDLCType, DLCManifest, DLCState
    from .dlc import BrainDLC
    from .core import BrainCore

__version__ = "2.1.0"

__all__ = [
    "BrainDLCType",
    "DLCState",
    "DLCManifest",
    "BrainDLC",
    "BrainCore",

]

__lazy_imports: dict[str, Any] = {}


def __getattr__(name: str) -> Any:
    if name in __lazy_imports:
        return __lazy_imports[name]

    if name in ("BrainDLCType", "DLCManifest", "DLCState"):
        from .models import BrainDLCType, DLCManifest, DLCState
        __lazy_imports["BrainDLCType"] = BrainDLCType
        __lazy_imports["DLCManifest"] = DLCManifest
        __lazy_imports["DLCState"] = DLCState
        return __lazy_imports[name]

    if name == "BrainDLC":
        from .dlc import BrainDLC
        __lazy_imports["BrainDLC"] = BrainDLC
        return BrainDLC

    if name == "BrainCore":
        from .core import BrainCore
        __lazy_imports["BrainCore"] = BrainCore
        return BrainCore

    if name == "discover_dlc_classes_from_package":
        from .discovery import discover_dlc_classes_from_package
        __lazy_imports["discover_dlc_classes_from_package"] = discover_dlc_classes_from_package
        return discover_dlc_classes_from_package

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
