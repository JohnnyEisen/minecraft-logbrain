from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Type

from .dlc import BrainDLC

# ── DLC 安全验证 ──────────────────────────────────────────────
# VULN-001 修复: DLC 文件加载前进行 AST 安全分析
# 防止恶意 DLC 通过 exec_module 获得任意代码执行

_DLC_FORBIDDEN_CALLS = frozenset({
    "exec", "eval", "compile", "__import__",
    "os.system", "os.popen", "subprocess.call", "subprocess.run",
    "subprocess.Popen", "subprocess.check_call", "subprocess.check_output",
    "socket.socket", "socket.create_connection",
    "urllib.request.urlopen", "requests.get", "requests.post",
    "shutil.rmtree", "shutil.move",
    "ctypes.CDLL", "ctypes.WinDLL",
})

_DLC_FORBIDDEN_IMPORTS = frozenset({
    "ctypes", "pty", "tty", "smtplib", "subprocess", "socket",
})

_DLC_MAX_FILE_BYTES = 512 * 1024  # 512KB

logger = logging.getLogger(__name__)


def _validate_dlc_source(code: str, file_path: Path) -> tuple[bool, str]:
    """对 DLC 源文件进行安全验证。

    Returns:
        (is_safe, error_message)
    """
    if len(code.encode("utf-8")) > _DLC_MAX_FILE_BYTES:
        return False, f"DLC 文件过大 ({len(code.encode('utf-8'))} bytes > {_DLC_MAX_FILE_BYTES})"

    try:
        tree = ast.parse(code, filename=str(file_path))
    except SyntaxError as e:
        return False, f"DLC 语法错误: {e}"

    class _DLCSecurityVisitor(ast.NodeVisitor):
        def __init__(self):
            self.violations: list[str] = []

        def visit_Call(self, node: ast.Call):
            parts = []
            cur = node.func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            full_name = ".".join(reversed(parts))

            if full_name in _DLC_FORBIDDEN_CALLS:
                self.violations.append(f"禁止的调用: {full_name}()")
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if base in _DLC_FORBIDDEN_IMPORTS:
                    self.violations.append(f"禁止的导入: {alias.name}")
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module:
                base = node.module.split(".")[0]
                if base in _DLC_FORBIDDEN_IMPORTS:
                    self.violations.append(f"禁止的导入: {node.module}")
            self.generic_visit(node)

    visitor = _DLCSecurityVisitor()
    visitor.visit(tree)

    if visitor.violations:
        return False, "; ".join(visitor.violations)
    return True, ""


def iter_dlc_files(search_paths: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for search_path in search_paths:
        path = Path(search_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            continue
        files.extend(sorted(p for p in path.glob("*.py") if p.is_file()))
    return files


def load_dlc_classes_from_file(file_path: Path) -> List[Type[BrainDLC]]:
    """从文件加载 DLC 子类（只返回类，不实例化）。

    加载完成后清理临时模块，避免 sys.modules 膨胀。
    VULN-001 修复: 加载前进行 AST 安全验证。
    """
    # ── VULN-001: 安全验证 ──
    try:
        source_code = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("无法读取 DLC 文件 %s: %s", file_path, e)
        return []

    is_safe, error = _validate_dlc_source(source_code, file_path)
    if not is_safe:
        logger.warning("DLC 安全验证失败 %s: %s", file_path.name, error)
        return []

    # ── 加载模块 ──
    module_name = f"brain_dlc_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        return []

    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    try:
        spec.loader.exec_module(module)
        return _extract_dlc_classes(module)
    finally:
        # 清理临时模块，防止 sys.modules 膨胀和名称冲突
        sys.modules.pop(module.__name__, None)


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
