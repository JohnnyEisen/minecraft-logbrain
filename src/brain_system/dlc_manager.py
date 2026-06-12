"""
DLC 管理器模块

从 BrainCore 提取的 DLC 管理逻辑，负责：
    - DLC 注册 / 注销
    - DLC 启用 / 禁用 / 挂起 / 恢复
    - DLC 文件加载与签名验证
    - DLC 依赖拓扑排序
    - DLC 状态查询

设计原则:
    - 单一职责：只管理 DLC 生命周期
    - 依赖注入：通过 core 引用访问 BrainCore 基础设施
    - 向后兼容：BrainCore 通过委托保持原有 API 不变
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Type

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .discovery import iter_dlc_files, load_dlc_classes_from_file
from .dlc import BrainDLC
from .models import DLCManifest, DLCState

if TYPE_CHECKING:
    from .core import BrainCore

logger = logging.getLogger(__name__)


class DLCManager:
    """DLC 管理器 —— 负责 DLC 的注册、加载、状态管理和依赖解析。

    从 BrainCore 中提取，降低其复杂度。
    通过 core 引用访问 BrainCore 的基础设施（配置、日志等）。
    """

    def __init__(self, core: "BrainCore") -> None:
        self._core = core
        self.dlcs: Dict[str, BrainDLC] = {}
        self.dlc_manifests: Dict[str, DLCManifest] = {}
        self.dlc_dependencies: Dict[str, Set[str]] = {}
        # 拓扑排序缓存
        self._topology_cache: Optional[Dict[str, list[str]]] = None
        self._topology_sorted: Optional[list[str]] = None

    # ---------------- 注册 / 注销 ----------------

    def register(self, dlc: BrainDLC) -> None:
        """注册一个 DLC 实例。"""
        manifest = dlc.get_manifest()
        core = self._core

        if bool(core.config.get("dlc_strict_dependency_check", True)):
            core_aliases = core.CORE_ALIASES | {core.name}
            for dep in manifest.dependencies:
                core._validate_dependency(dep)
                dep_name, _ = core._parse_dependency(dep)
                if dep_name and dep_name not in core_aliases:
                    dep_dlc = self.dlcs.get(dep_name)
                    if dep_dlc is None:
                        raise RuntimeError(f"依赖 DLC 未加载: {dep_name}")
                    if dep_dlc.state in (DLCState.FAILED, DLCState.UNLOADED):
                        raise RuntimeError(
                            f"依赖 DLC 未就绪: {dep_name} (state={dep_dlc.state.value})"
                        )

        if manifest.name in self.dlcs:
            logging.warning("DLC 已存在，将替换: %s", manifest.name)
            self.unregister(manifest.name)

        self.dlcs[manifest.name] = dlc
        self.dlc_manifests[manifest.name] = manifest
        self.dlc_dependencies[manifest.name] = set(manifest.dependencies)

        dlc.initialize()
        logging.info(
            "已注册DLC: %s v%s (state=%s)",
            manifest.name,
            manifest.version,
            dlc.state.value,
        )

    def unregister(self, name: str) -> None:
        """注销指定 DLC。"""
        dlc = self.dlcs.pop(name, None)
        self.dlc_manifests.pop(name, None)
        self.dlc_dependencies.pop(name, None)
        if dlc is not None:
            try:
                dlc.shutdown()
            except Exception as e:
                logging.warning("DLC shutdown failed for %s: %s", name, e)

    # ---------------- 状态控制 ----------------

    def enable(self, name: str) -> bool:
        dlc = self.dlcs.get(name)
        if dlc is None:
            logging.warning("DLC 不存在: %s", name)
            return False
        try:
            dlc.enable()
            logging.info("DLC 已启用: %s (state=%s)", name, dlc.state.value)
            return True
        except Exception as e:
            logging.error("启用 DLC 失败 %s: %s", name, e)
            return False

    def disable(self, name: str) -> bool:
        dlc = self.dlcs.get(name)
        if dlc is None:
            logging.warning("DLC 不存在: %s", name)
            return False
        try:
            dlc.disable()
            logging.info("DLC 已禁用: %s (state=%s)", name, dlc.state.value)
            return True
        except Exception as e:
            logging.error("禁用 DLC 失败 %s: %s", name, e)
            return False

    def suspend(self, name: str) -> bool:
        dlc = self.dlcs.get(name)
        if dlc is None:
            logging.warning("DLC 不存在: %s", name)
            return False
        try:
            dlc.suspend()
            logging.info("DLC 已挂起: %s (state=%s)", name, dlc.state.value)
            return True
        except Exception as e:
            logging.error("挂起 DLC 失败 %s: %s", name, e)
            return False

    def resume(self, name: str) -> bool:
        dlc = self.dlcs.get(name)
        if dlc is None:
            logging.warning("DLC 不存在: %s", name)
            return False
        try:
            dlc.resume()
            logging.info("DLC 已恢复: %s (state=%s)", name, dlc.state.value)
            return True
        except Exception as e:
            logging.error("恢复 DLC 失败 %s: %s", name, e)
            return False

    # ---------------- 文件加载 ----------------

    def load_dlc_file(self, dlc_path: str, *, allow_replace: bool = False) -> int:
        """从文件加载 DLC，返回成功注册的 DLC 类数量。"""
        core = self._core
        path = Path(dlc_path)
        if not path.exists() or not path.is_file():
            return 0

        if not core._verify_dlc_file_signature(path):
            return 0

        try:
            classes = load_dlc_classes_from_file(path)
        except Exception as e:
            logging.error("加载DLC失败 %s: %s", path.name, type(e).__name__)
            return 0

        count = 0
        for cls in classes:
            try:
                inst = cls(core)
                manifest = inst.get_manifest()
                if allow_replace and manifest.name in self.dlcs:
                    self.unregister(manifest.name)
                self.register(inst)
                count += 1
            except Exception as e:
                logging.error(
                    "注册DLC失败 %s(%s): %s", path.name, cls.__name__, type(e).__name__
                )

        if core.obs.metrics_enabled and core.obs.dlc_loaded is not None:
            try:
                core.obs.dlc_loaded.inc(count)
            except Exception as e:
                logging.debug("Failed to increment dlc_loaded metric: %s", e)
        return count

    def reload_dlc_file(self, dlc_path: str) -> tuple[int, bool]:
        """热升级：卸载同名 DLC，再加载新版本，支持回滚。

        Returns:
            tuple[int, bool]: (成功注册数量, 是否成功)
        """
        core = self._core
        path = Path(dlc_path)
        if not path.exists() or not path.is_file():
            return 0, False

        if not core._verify_dlc_file_signature(path):
            return 0, False

        try:
            classes = load_dlc_classes_from_file(path)
        except Exception as e:
            logging.error("加载DLC失败 %s: %s", path.name, type(e).__name__)
            return 0, False

        # 备份现有 DLC 以便回滚
        backup: dict[str, tuple[BrainDLC, DLCManifest, set[str]]] = {}
        for cls in classes:
            try:
                inst = cls(core)
                manifest = inst.get_manifest()
                if manifest.name in self.dlcs:
                    backup[manifest.name] = (
                        self.dlcs[manifest.name],
                        self.dlc_manifests[manifest.name],
                        self.dlc_dependencies[manifest.name],
                    )
            except Exception:
                pass

        # 尝试加载新版本
        count = 0
        failed = False
        loaded_names: list[str] = []

        for cls in classes:
            try:
                inst = cls(core)
                manifest = inst.get_manifest()
                if manifest.name in self.dlcs:
                    self.unregister(manifest.name)
                self.register(inst)
                loaded_names.append(manifest.name)
                count += 1
            except Exception as e:
                logging.error(
                    "注册DLC失败 %s(%s): %s", path.name, cls.__name__, type(e).__name__
                )
                failed = True
                break

        if failed:
            logging.warning("DLC热加载失败，正在回滚...")
            for name in loaded_names:
                try:
                    self.unregister(name)
                except Exception:
                    pass

            for name, (old_dlc, old_manifest, old_deps) in backup.items():
                try:
                    # VULN-007 fix: shutdown 后需重新初始化
                    if old_dlc.state in (DLCState.UNLOADED, DLCState.DISABLED):
                        old_dlc._initialized = False
                        old_dlc._state = DLCState.UNLOADED
                        old_dlc.initialize()
                    self.dlcs[name] = old_dlc
                    self.dlc_manifests[name] = old_manifest
                    self.dlc_dependencies[name] = old_deps
                    logging.info("已回滚DLC: %s (state=%s)", name, old_dlc.state.value)
                except Exception as e:
                    logging.error("回滚DLC失败 %s: %s", name, e)

            return 0, False

        if core.obs.metrics_enabled and core.obs.dlc_loaded is not None:
            try:
                core.obs.dlc_loaded.inc(count)
            except Exception as e:
                logging.debug("Failed to increment dlc_loaded metric: %s", e)

        return count, True

    def load_all(self, search_paths: Optional[list[str]] = None) -> int:
        """从搜索路径加载所有 DLC。

        使用拓扑排序确保依赖 DLC 先于被依赖 DLC 加载。
        每个 DLC 类只实例化一次，避免重复创建。
        """
        core = self._core
        paths = search_paths or list(core.config.get("dlc_search_paths", ["./dlcs"]))
        dlc_files = iter_dlc_files(paths)

        # 避免把本包源码目录误选为 DLC 目录
        try:
            package_dir = Path(__file__).resolve().parent
            dlc_files = [
                p for p in dlc_files
                if not p.resolve().is_relative_to(package_dir)
            ]
        except Exception as e:
            logging.debug(
                "Path.is_relative_to not available (Python < 3.9?): %s", e
            )

        # 第一阶段：发现所有 DLC 文件
        pending_cls: list[type[BrainDLC]] = []
        for file_path in dlc_files:
            if not core._verify_dlc_file_signature(file_path):
                continue
            try:
                classes = load_dlc_classes_from_file(file_path)
                pending_cls.extend(classes)
            except Exception as e:
                logging.error("读取 DLC 类失败 %s: %s", file_path, e)

        # 第二阶段：解析 manifest，构建依赖图
        graph: dict[str, list[str]] = {}
        priority_map: dict[str, int] = {}
        name_to_cls: dict[str, type[BrainDLC]] = {}
        core_aliases = core.CORE_ALIASES | {core.name}

        for cls in pending_cls:
            temp_inst = None
            try:
                temp_inst = cls(core)
                manifest = temp_inst.get_manifest()
                name = manifest.name
                priority_map[name] = int(manifest.priority)

                deps: list[str] = []
                for dep_raw in manifest.dependencies:
                    dep_name, _ = core._parse_dependency(dep_raw)
                    if dep_name and dep_name not in core_aliases:
                        deps.append(dep_name)

                graph[name] = deps
                name_to_cls[name] = cls
            except Exception as e:
                logging.debug(
                    "解析 DLC 清单失败 %s: %s",
                    getattr(cls, "__name__", str(cls)),
                    e,
                )
            finally:
                if temp_inst is not None:
                    try:
                        temp_inst._pre_shutdown()
                    except Exception:
                        pass

        # 第三阶段：拓扑排序
        sorted_names = core._topological_sort(graph, priority_map)
        if sorted_names is None:
            logging.error("DLC 依赖图存在循环依赖，无法加载")
            return 0

        # 第四阶段：按排序顺序注册
        loaded = 0
        for name in sorted_names:
            cls = name_to_cls.get(name)
            if cls is None:
                continue
            try:
                inst = cls(core)
                self.register(inst)
                loaded += 1
            except Exception as e:
                logging.error("DLC 注册失败 %s: %s", name, e)

        logging.info("已加载 %d 个DLC（来自 %d 个文件）", loaded, len(dlc_files))
        return loaded

    # ---------------- 状态查询 ----------------

    def get_status(self) -> Dict[str, Any]:
        """获取所有 DLC 的状态信息。"""
        status: Dict[str, Any] = {}
        for name, dlc in self.dlcs.items():
            manifest = self.dlc_manifests[name]
            status[name] = {
                "version": manifest.version,
                "type": manifest.dlc_type.value,
                "enabled": dlc.enabled,
                "state": dlc.state.value,
                "dependencies": list(self.dlc_dependencies[name]),
                "initialized": bool(getattr(dlc, "_initialized", False)),
            }
        return status

    def get_computational_unit(self, unit_type: str) -> Any:
        """从 DLC 获取计算单元。"""
        # 先查缓存
        if unit_type in self._core.computational_units:
            return self._core.computational_units[unit_type]

        for dlc in self.dlcs.values():
            units = dlc.provide_computational_units()
            if unit_type in units:
                self._core.computational_units[unit_type] = units[unit_type]
                return units[unit_type]

        raise ValueError(f"未找到计算单元类型: {unit_type}")

    def notify_config_changed(self) -> None:
        """通知所有已激活的 DLC 配置已变更。"""
        for dlc in self.dlcs.values():
            try:
                if dlc.state in (DLCState.ACTIVE, DLCState.SUSPENDED):
                    dlc.on_config_changed(dict(self._core.config))
            except Exception as e:
                logging.debug(
                    "DLC %s 配置更新通知失败: %s", dlc.manifest.name, e
                )