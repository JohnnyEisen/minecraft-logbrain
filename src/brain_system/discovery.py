from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Type

from .dlc import BrainDLC


def iter_dlc_files(search_paths: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for search_path in search_paths:
        path = Path(search_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            continue
        files.extend(sorted(p for p in path.glob("*.py") if p.is_file()))
    return files


def load_dlc_classes_from_file(file_path: Path) -> List[Type[BrainDLC]]:
    """从文件加载 DLC 子类（只返回类，不实例化）。"""

    module_name = f"brain_dlc_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        return []

    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    spec.loader.exec_module(module)

    return _extract_dlc_classes(module)


def load_dlc_classes_from_module(module_name: str) -> List[Type[BrainDLC]]:
    """从已安装的 Python 模块中加载 DLC 子类。

    Args:
        module_name: 模块全限定名（如 ``dlcs.brain_dlc_distributed``）。

    Returns:
        BrainDLC 子类列表。
    """
    try:
        module = importlib.import_module(module_name)
        return _extract_dlc_classes(module)
    except Exception:
        return []


def discover_dlc_classes_from_package(package_name: str) -> List[Type[BrainDLC]]:
    """从 Python 包中递归发现所有 DLC 子类。

    Args:
        package_name: 包名（如 ``dlcs``）。

    Returns:
        BrainDLC 子类列表。
    """
    classes: List[Type[BrainDLC]] = []
    try:
        package = importlib.import_module(package_name)
        if not hasattr(package, "__path__"):
            return []

        for _, module_name, is_pkg in pkgutil.walk_packages(
            package.__path__, prefix=package_name + "."
        ):
            if is_pkg:
                continue
            try:
                module = importlib.import_module(module_name)
                classes.extend(_extract_dlc_classes(module))
            except Exception:
                continue
    except Exception:
        return []
    return classes


def _extract_dlc_classes(module) -> List[Type[BrainDLC]]:
    """从模块中提取 BrainDLC 子类。"""
    classes: List[Type[BrainDLC]] = []
    for _, obj in vars(module).items():
        if inspect.isclass(obj) and issubclass(obj, BrainDLC) and obj is not BrainDLC:
            classes.append(obj)
    return classes
