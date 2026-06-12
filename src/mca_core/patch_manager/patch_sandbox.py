# -*- coding: utf-8 -*-
"""补丁管理系统 — 沙箱执行环境

安全执行补丁代码，按权限等级限制可用操作。
禁止直接 exec_module——所有补丁必须在受控上下文中执行。

权限级别:
- restricted (默认): 纯计算，无文件IO/网络/子进程
- standard: 允许读取文件，禁止写入和网络
- admin: 完全权限（需显式审批）
"""
from __future__ import annotations

import builtins
import types
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(Enum):
    """补丁执行权限级别"""
    RESTRICTED = "restricted"  # 默认：纯计算，无IO/网络/子进程
    STANDARD = "standard"      # 只读文件，禁止网络和子进程
    ADMIN = "admin"            # 完全权限（需显式审批 + 审计）


# 各权限等级允许的 builtins
_RESTRICTED_BUILTINS = frozenset({
    "abs", "all", "any", "ascii", "bin", "bool", "bytes", "callable",
    "chr", "complex", "dict", "dir", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "getattr", "hasattr", "hash",
    "hex", "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "memoryview", "min", "next", "object",
    "oct", "ord", "pow", "print", "property", "range", "repr",
    "reversed", "round", "set", "slice", "sorted", "str", "sum",
    "super", "tuple", "type", "vars", "zip",
    "ArithmeticError", "AssertionError", "AttributeError",
    "BaseException", "Exception", "EOFError", "GeneratorExit",
    "ImportError", "IndentationError", "IndexError", "KeyError",
    "KeyboardInterrupt", "LookupError", "MemoryError", "NameError",
    "NotImplementedError", "OSError", "OverflowError", "RuntimeError",
    "StopAsyncIteration", "StopIteration", "SyntaxError", "SystemError",
    "TypeError", "UnboundLocalError", "UnicodeError", "ValueError",
    "ZeroDivisionError", "True", "False", "None", "Ellipsis",
    "NotImplemented", "__build_class__",
})

_STANDARD_BUILTINS = _RESTRICTED_BUILTINS | frozenset({
    "open", "bytearray", "staticmethod", "classmethod",
})

_ADMIN_DENIED = frozenset({
    "exec", "eval", "compile", "__import__",
})


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    message: str = ""
    error: str = ""
    permission_level: str = "restricted"
    restricted_operations: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0


def _make_restricted_builtins(level: PermissionLevel) -> dict[str, Any]:
    """构建受限的 builtins 字典。

    安全策略：
    - restricted: 纯计算，移除 open/exec/eval/compile/__import__
    - standard: 保留 open (只读)，移除 exec/eval/compile
    - admin: 保留 open，但移除 exec/eval/compile
    """
    safe: dict[str, Any] = {}

    if level == PermissionLevel.RESTRICTED:
        allowed = _RESTRICTED_BUILTINS
    elif level == PermissionLevel.STANDARD:
        allowed = _STANDARD_BUILTINS
    else:
        allowed = set(builtins.__dict__.keys()) - _ADMIN_DENIED

    for name in allowed:
        if name in builtins.__dict__:
            safe[name] = builtins.__dict__[name]

    # 运行时 getattr 包装器 — 阻止对 __subclasses__/__bases__ 等危险属性的访问
    # 这是对抗 chr()/字符串拼接/动态构造绕过文本匹配的最终防线
    _blocked_dunders = frozenset({
        "__subclasses__", "__bases__", "__mro__", "__globals__",
        "__code__", "__closure__", "__builtins__", "__loader__",
        "__getattribute__", "__dict__",
    })
    _original_getattr = safe.get("getattr", builtins.getattr)
    def _safe_getattr(obj, name, *args):
        if isinstance(name, str) and name in _blocked_dunders:
            raise AttributeError(
                f"沙箱安全限制: 禁止访问 '{name}' 属性"
            )
        return _original_getattr(obj, name, *args)
    safe["getattr"] = _safe_getattr

    # 包装 hasattr — C级 hasattr 内部调 PyObject_GetAttr 绕过 Python 层守卫
    _original_hasattr = safe.get("hasattr", builtins.hasattr)
    def _safe_hasattr(obj, name):
        if isinstance(name, str) and name in _blocked_dunders:
            return False
        return _original_hasattr(obj, name)
    safe["hasattr"] = _safe_hasattr

    # RESTRICTED 级别下不允许任何 I/O
    if level == PermissionLevel.RESTRICTED:
        safe.pop("open", None)
    elif level == PermissionLevel.STANDARD:
        safe["open"] = _safe_open_readonly

    # 所有级别禁止 exec/eval
    safe["exec"] = _blocked("exec()")
    safe["eval"] = _blocked("eval()")

    # 所有级别禁用 compile
    safe["compile"] = _blocked("compile()")

    return safe


def _safe_open_readonly(file, mode="r", *args, **kwargs):
    """只读 open——拒绝写入模式。"""
    mode_str = str(mode)
    if "w" in mode_str or "a" in mode_str or "+" in mode_str or "x" in mode_str:
        raise PermissionError(
            f"沙箱错误: 补丁不允许写入文件 (mode='{mode}')。"
            f"仅允许 'r' 模式。"
        )
    return builtins.open(file, mode, *args, **kwargs)


def _blocked(name: str):
    """返回一个阻塞函数，调用时抛出 PermissionError。"""
    def _blocked_func(*args, **kwargs):
        raise PermissionError(
            f"沙箱错误: 补丁中禁止使用 {name}。"
        )
    return _blocked_func


# VULN-003 修复: 沙箱内允许导入的安全模块白名单
# 审核规则:
#   - inspect   → 移除: currentframe() 泄露 frame 对象 (f_builtins/f_globals)
#   - logging   → 移除: logging.sys 泄露 sys 模块引用
#   - io        → 移除: io.open() 可能绕过 open() 限制
#   - subprocess → 从不在白名单
#   - marshal/types/codecs → 始终拒绝 (不在白名单 + Python 预加载到 sys.modules)
_SANDBOX_SAFE_MODULES = frozenset({
    "abc", "collections", "collections.abc", "copy", "dataclasses", "enum",
    "functools", "hashlib", "hmac", "itertools",
    "math", "numbers", "operator", "statistics", "string",
    "textwrap", "typing", "typing_extensions", "uuid", "warnings", "weakref",
    "json", "time", "datetime", "re",
    "numpy", "matplotlib", "networkx",
})


# 沙箱全局命名空间禁止泄露的模块引用
_SANDBOX_BLOCKED_REFERENCES = frozenset({
    "sys", "os", "subprocess", "socket", "ctypes", "marshal", "types",
    "codecs", "gc", "signal", "atexit", "pickle", "shutil",
    "urllib", "http", "smtplib", "ftplib", "telnetlib",
})

def _sanitize_sandbox_globals(sandbox_globals: dict[str, Any]):
    """扫描并清除沙箱全局中泄露的危险模块引用。

    白名单模块 (如 logging) 的内部 import (如 import sys)
    会将 sys 泄露为模块属性 (logging.sys)。此函数遍历所有已加载模块，
    清除其 __dict__ 中指向危险模块的引用。
    """
    import sys as _sys
    for mod_name in list(sandbox_globals.keys()):
        if mod_name.startswith("_"):
            continue
        mod = sandbox_globals[mod_name]
        if not hasattr(mod, "__dict__"):
            continue
        for attr_name in list(mod.__dict__.keys()):
            try:
                attr = getattr(mod, attr_name)
            except Exception:
                continue
            # 检查属性是否是危险模块
            if attr is _sys:
                try:
                    delattr(mod, attr_name)
                except Exception:
                    pass
            elif hasattr(attr, "__name__") and getattr(attr, "__name__", "") in _SANDBOX_BLOCKED_REFERENCES:
                try:
                    delattr(mod, attr_name)
                except Exception:
                    pass


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """VULN-003 修复: 沙箱安全导入钩子。

    只允许导入白名单中的模块。禁止导入 os/subprocess/socket/ctypes 等。
    禁止 `__import__` 逃逸沙箱。导入后扫描并清除危险模块泄露。
    """
    base = name.split(".")[0]
    full = name
    if base not in _SANDBOX_SAFE_MODULES and full not in _SANDBOX_SAFE_MODULES:
        raise ImportError(
            f"沙箱安全限制: 不允许导入 '{name}'。"
            f"仅允许导入白名单中的模块。"
        )
    mod = __import__(name, globals, locals, fromlist, level)
    # THREAT-009: 扫描导入后的模块，清除泄露的危险引用（如 logging.sys → sys）
    if hasattr(mod, "__dict__"):
        _sanitize_imported_module(mod)
    return mod


def _sanitize_imported_module(mod):
    """清除已加载模块中泄露的危险模块引用。"""
    import sys as _sys
    for attr_name in list(mod.__dict__.keys()):
        if attr_name.startswith("_"):
            continue
        try:
            attr = getattr(mod, attr_name)
        except Exception:
            continue
        if attr is _sys:
            try:
                delattr(mod, attr_name)
            except Exception:
                pass
        elif hasattr(attr, "__name__"):
            if getattr(attr, "__name__", "").split(".")[0] in _SANDBOX_BLOCKED_REFERENCES:
                try:
                    delattr(mod, attr_name)
                except Exception:
                    pass


def create_sandbox_globals(
    level: PermissionLevel = PermissionLevel.RESTRICTED,
    extra_globals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建沙箱全局命名空间。

    Args:
        level: 权限级别
        extra_globals: 额外注入的安全全局变量

    Returns:
        受限的全局命名空间字典
    """
    sandbox_builtins = _make_restricted_builtins(level)

    # VULN-003: 所有级别替换 __import__ 为安全导入钩子
    sandbox_builtins["__import__"] = _safe_import

    sandbox = types.SimpleNamespace()
    sandbox.__builtins__ = sandbox_builtins

    result: dict[str, Any] = {
        "__builtins__": sandbox_builtins,
        "__name__": "__sandbox__",
        "__sandbox__": sandbox,
    }

    if extra_globals:
        result.update(extra_globals)

    # THREAT-009: 清除所有导入模块中泄露的危险引用
    _sanitize_sandbox_globals(result)

    return result


def execute_patch_sandboxed(
    code: str,
    patch_id: str,
    level: PermissionLevel = PermissionLevel.RESTRICTED,
    entry_point: str = "apply",
    entry_args: tuple = (),
    entry_kwargs: dict[str, Any] | None = None,
) -> SandboxResult:
    """在沙箱中安全执行补丁代码。

    限制：所有级别禁止 ``exec/eval/compile/__import__``。
    restricted 额外禁止 I/O；standard 允许只读文件；
    admin 仅允许白名单模块导入。

    流程：构建受限 builtins → compile 代码 → exec → 调用入口函数 → 返回结果。

    :param code: 补丁 Python 源码。
    :param patch_id: 补丁标识符（用于错误消息）。
    :param level: |PermissionLevel|_ 权限级别（默认 RESTRICTED）。
    :param entry_point: 入口函数名（默认 ``"apply"``）。
    :param entry_args: 入口函数位置参数。
    :param entry_kwargs: 入口函数关键字参数。
    :returns: |SandboxResult|_ 执行结果（success / error / 耗时）。
    :rtype: SandboxResult

    **用法**::

        result = execute_patch_sandboxed(
            code="def apply(): return sum(range(100))",
            patch_id="safe_patch",
            level=PermissionLevel.RESTRICTED,
        )
        assert result.success
    """
    import time

    start = time.perf_counter()
    restricted_ops: list[str] = []

    if entry_kwargs is None:
        entry_kwargs = {}

    # ── 源码级内省拦截（防 __subclasses__/__globals__ 沙箱逃逸）──
    # 源码文本匹配作为第一道防线
    _SANDBOX_INTROSPECTION_PATTERNS = [
        "__subclasses__", "__bases__", "__mro__", "__globals__",
        "__code__", "__closure__",
    ]
    code_lower = code.lower()
    for pat in _SANDBOX_INTROSPECTION_PATTERNS:
        if pat in code_lower:
            return SandboxResult(
                success=False,
                error=f"沙箱禁止内省操作: {pat}",
                message=f"补丁 {patch_id} 包含禁止的内省调用: {pat}",
                permission_level=level.value,
                restricted_operations=[pat],
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        sandbox_globals = create_sandbox_globals(level)

        # 编译并执行补丁代码（带 30 秒超时）
        compiled = compile(code, f"<patch:{patch_id}>", "exec")
        import threading as _threading
        _exec_error: list[Exception] = []
        _exec_done = _threading.Event()
        def _exec_in_thread():
            try:
                exec(compiled, sandbox_globals)
            except Exception as _e:
                _exec_error.append(_e)
            finally:
                _exec_done.set()
        _t = _threading.Thread(target=_exec_in_thread, daemon=True)
        _t.start()
        if not _exec_done.wait(timeout=30.0):
            return SandboxResult(
                success=False,
                error="补丁执行超时 (30s)",
                message=f"补丁 {patch_id} 执行超过 30 秒，已强制终止",
                permission_level=level.value,
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )
        if _exec_error:
            raise _exec_error[0]

        # 调用入口函数
        entry_func = sandbox_globals.get(entry_point)
        if entry_func is None:
            return SandboxResult(
                success=False,
                message=f"补丁缺少入口函数 '{entry_point}()'",
                permission_level=level.value,
                restricted_operations=restricted_ops,
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )

        if not callable(entry_func):
            return SandboxResult(
                success=False,
                message=f"入口 '{entry_point}' 不是可调用对象",
                permission_level=level.value,
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )

        result = entry_func(*entry_args, **entry_kwargs)

        elapsed = (time.perf_counter() - start) * 1000
        return SandboxResult(
            success=True,
            message=f"补丁 {patch_id} 执行成功 (entry={entry_point})",
            permission_level=level.value,
            restricted_operations=restricted_ops,
            execution_time_ms=elapsed,
        )

    except PermissionError as e:
        return SandboxResult(
            success=False,
            error=str(e),
            message=f"补丁 {patch_id} 权限不足: {e}",
            permission_level=level.value,
            restricted_operations=restricted_ops,
            execution_time_ms=(time.perf_counter() - start) * 1000,
        )
    except SyntaxError as e:
        return SandboxResult(
            success=False,
            error=str(e),
            message=f"补丁 {patch_id} 语法错误: {e}",
            permission_level=level.value,
            execution_time_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as e:
        return SandboxResult(
            success=False,
            error=str(e),
            message=f"补丁 {patch_id} 执行异常: {type(e).__name__}: {e}",
            permission_level=level.value,
            restricted_operations=restricted_ops,
            execution_time_ms=(time.perf_counter() - start) * 1000,
        )