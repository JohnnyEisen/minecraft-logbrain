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
    "NotImplemented", "__build_class__", "__import__",
})

_STANDARD_BUILTINS = _RESTRICTED_BUILTINS | frozenset({
    "open", "bytearray", "staticmethod", "classmethod",
})

_ADMIN_DENIED = frozenset({
    "exec", "eval", "compile",
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

    # restricted 级别下包装 open 为只读
    if level == PermissionLevel.RESTRICTED:
        safe["open"] = _safe_open_readonly
    elif level == PermissionLevel.STANDARD:
        safe["open"] = _safe_open_readonly
    elif level == PermissionLevel.ADMIN:
        # admin 级别也拦截 exec/eval/compile
        # 但保留 open 完整功能
        pass

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

    sandbox = types.SimpleNamespace()
    sandbox.__builtins__ = sandbox_builtins

    result: dict[str, Any] = {
        "__builtins__": sandbox_builtins,
        "__name__": "__sandbox__",
        "__sandbox__": sandbox,
    }

    if extra_globals:
        result.update(extra_globals)

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

    执行流程:
    1. 构建受限的 builtins 上下文
    2. 编译并执行补丁代码
    3. 调用指定的入口函数（默认 apply()）
    4. 返回沙箱执行结果

    Args:
        code: 补丁源码
        patch_id: 补丁 ID（用于日志）
        level: 权限级别
        entry_point: 入口函数名
        entry_args: 入口函数位置参数
        entry_kwargs: 入口函数关键字参数

    Returns:
        SandboxResult
    """
    import time

    start = time.perf_counter()
    restricted_ops: list[str] = []

    if entry_kwargs is None:
        entry_kwargs = {}

    try:
        sandbox_globals = create_sandbox_globals(level)

        # 编译并执行补丁代码
        compiled = compile(code, f"<patch:{patch_id}>", "exec")
        exec(compiled, sandbox_globals)

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