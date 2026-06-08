# -*- coding: utf-8 -*-
"""补丁管理系统 — 代码安全验证器

在上传补丁前执行严格的代码审查：
1. AST 静态分析——检测危险操作（exec/eval/subprocess/os.system/文件写入/网络）
2. 接口验证——确保补丁定义了必需的入口函数
3. 导入白名单——只允许安全模块的导入
4. 风险评估——根据检测到的操作自动分类风险等级
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(Enum):
    """补丁代码风险等级"""
    SAFE = "safe"            # 纯计算，无危险操作
    LOW = "low"              # 有文件读取，无写入/网络
    MEDIUM = "medium"        # 有文件写入，无网络/子进程
    HIGH = "high"            # 有网络或子进程，但无系统级操作
    CRITICAL = "critical"    # 有系统级操作（exec/eval/os.system/subprocess）
    REJECTED = "rejected"    # 包含被禁止的操作，拒绝上传


# ── 危险操作分类 ──────────────────────────────────────────

# 被完全禁止的操作（任何级别都不允许）
_FORBIDDEN_FUNCTIONS: set[str] = {
    "exec", "eval", "compile",
    "__import__", "importlib.import_module",
}

# 高危操作——需要 admin 权限
_HIGH_RISK_FUNCTIONS: set[str] = {
    "os.system", "os.popen", "os.spawnl", "os.spawnle", "os.spawnlp",
    "os.spawnlpe", "os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "subprocess.check_call", "subprocess.check_output",
    "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "shutil.rmtree", "shutil.move", "shutil.copy",
    "os.chmod", "os.chown", "os.kill", "os.abort",
    "ctypes.CDLL", "ctypes.WinDLL", "ctypes.OleDLL",
    "socket.socket", "socket.create_connection",
    "urllib.request", "http.client",
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.patch", "requests.head", "requests.options",
}

# 中危操作——需要 standard 权限
_MEDIUM_RISK_FUNCTIONS: set[str] = {
    "open", "builtins.open",
    "os.mkdir", "os.makedirs",
    "os.rename", "os.replace",
    "json.dump", "json.dumps",
    "pickle.dump", "pickle.dumps",
}

# 高危导入模块
_HIGH_RISK_IMPORTS: set[str] = {
    "os", "subprocess", "shutil", "ctypes",
    "socket", "urllib", "http", "requests",
    "ftplib", "smtplib", "telnetlib",
    "multiprocessing", "threading",
    "signal",
}

# 中危导入模块
_MEDIUM_RISK_IMPORTS: set[str] = {
    "json", "pickle", "csv", "configparser",
    "pathlib", "glob", "fnmatch",
    "datetime", "time", "logging",
    "re", "sys",
}

# 安全导入模块（白名单）
_SAFE_IMPORTS: set[str] = {
    "abc", "collections", "collections.abc",
    "copy", "dataclasses", "enum",
    "functools", "hashlib", "hmac",
    "inspect", "io", "itertools",
    "math", "numbers", "operator",
    "random", "statistics", "string",
    "textwrap", "typing", "typing_extensions",
    "uuid", "warnings", "weakref",
}

# 补丁必需的入口函数
_REQUIRED_ENTRY_POINTS = frozenset({"apply", "rollback"})


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    risk_level: str = RiskLevel.SAFE.value
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_operations: list[str] = field(default_factory=list)
    detected_imports: list[str] = field(default_factory=list)
    detected_entry_points: list[str] = field(default_factory=list)
    summary: str = ""


class PatchValidator:
    """补丁代码安全验证器。

    使用 AST 静态分析扫描补丁代码，检测危险操作并分类风险等级。

    用法:
        validator = PatchValidator()
        result = validator.validate(patch_code)
        if not result.is_valid:
            print("拒绝原因:", result.errors)
    """

    # 可配置的阈值
    MAX_PATCH_SIZE_BYTES: int = 512 * 1024  # 512KB
    MAX_AST_NODES: int = 2000

    def validate(self, code: str, patch_id: str = "") -> ValidationResult:
        """对补丁代码执行完整安全验证。

        Args:
            code: 补丁源代码
            patch_id: 补丁 ID（用于错误消息）

        Returns:
            ValidationResult
        """
        errors: list[str] = []
        warnings: list[str] = []
        detected_ops: list[str] = []
        detected_imports: list[str] = []
        detected_entries: list[str] = []

        # 1. 基本检查
        if not code or not code.strip():
            return ValidationResult(
                is_valid=False,
                risk_level=RiskLevel.REJECTED.value,
                errors=[f"补丁 {patch_id}: 代码为空"],
                summary="空代码被拒绝",
            )

        if len(code.encode("utf-8")) > self.MAX_PATCH_SIZE_BYTES:
            return ValidationResult(
                is_valid=False,
                risk_level=RiskLevel.REJECTED.value,
                errors=[f"补丁 {patch_id}: 代码过大 ({len(code.encode('utf-8'))} bytes > {self.MAX_PATCH_SIZE_BYTES})"],
                summary="代码过大被拒绝",
            )

        # 2. AST 解析
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(
                is_valid=False,
                risk_level=RiskLevel.REJECTED.value,
                errors=[f"补丁 {patch_id}: 语法错误: {e}"],
                summary="语法错误被拒绝",
            )

        # 3. AST 节点数检查
        node_count = sum(1 for _ in ast.walk(tree))
        if node_count > self.MAX_AST_NODES:
            return ValidationResult(
                is_valid=False,
                risk_level=RiskLevel.REJECTED.value,
                errors=[f"补丁 {patch_id}: AST 节点数过多 ({node_count} > {self.MAX_AST_NODES})"],
                summary="代码过于复杂被拒绝",
            )

        # 4. 遍历 AST 收集信息
        collector = _ASTCollector()
        collector.visit(tree)

        detected_ops = list(collector.dangerous_calls)
        detected_imports = list(collector.imports)
        detected_entries = [
            name for name in _REQUIRED_ENTRY_POINTS
            if name in collector.defined_functions
        ]

        # 5. 检查禁止操作
        for call in collector.dangerous_calls:
            if call in _FORBIDDEN_FUNCTIONS:
                errors.append(
                    f"补丁 {patch_id}: 禁止使用 {call}()——所有权限级别均不允许"
                )

        # 6. 检查入口函数
        if "apply" not in collector.defined_functions:
            errors.append(
                f"补丁 {patch_id}: 缺少必需的入口函数 'apply()'。"
                f"补丁必须定义 def apply():"
            )

        # 7. 检查模块级代码（非函数/类定义）
        if collector.has_module_level_code:
            warnings.append(
                f"补丁 {patch_id}: 包含模块级可执行代码，"
                f"这些代码将在导入时立即执行。建议将所有逻辑放入 apply() 函数中。"
            )

        # 8. 确定风险等级
        risk = self._classify_risk(collector, errors)

        return ValidationResult(
            is_valid=len(errors) == 0,
            risk_level=risk.value,
            errors=errors,
            warnings=warnings,
            detected_operations=detected_ops,
            detected_imports=detected_imports,
            detected_entry_points=detected_entries,
            summary=self._build_summary(risk, errors, warnings, detected_ops, detected_entries),
        )

    def _classify_risk(self, collector: _ASTCollector, errors: list[str]) -> RiskLevel:
        """根据收集到的 AST 信息分类风险等级。"""
        if errors:
            return RiskLevel.REJECTED

        calls = collector.dangerous_calls

        # 检查禁止操作
        if any(c in _FORBIDDEN_FUNCTIONS for c in calls):
            return RiskLevel.REJECTED

        # 检查高危操作
        has_high_risk = any(c in _HIGH_RISK_FUNCTIONS for c in calls)
        has_high_import = any(
            imp in _HIGH_RISK_IMPORTS
            for imp in collector.imports
        )

        if has_high_risk or has_high_import:
            return RiskLevel.HIGH

        # 检查中危操作
        has_medium_risk = any(c in _MEDIUM_RISK_FUNCTIONS for c in calls)
        has_medium_import = any(
            imp in _MEDIUM_RISK_IMPORTS
            for imp in collector.imports
        )

        if has_medium_risk or has_medium_import:
            return RiskLevel.MEDIUM

        # 检查是否有任何非安全导入
        unsafe_imports = [
            imp for imp in collector.imports
            if imp not in _SAFE_IMPORTS
            and not any(imp.startswith(s + ".") for s in _SAFE_IMPORTS)
        ]
        if unsafe_imports:
            return RiskLevel.LOW

        return RiskLevel.SAFE

    def _build_summary(
        self,
        risk: RiskLevel,
        errors: list[str],
        warnings: list[str],
        ops: list[str],
        entries: list[str],
    ) -> str:
        """构建可读的验证摘要。"""
        parts = [f"风险等级: {risk.value}"]

        if errors:
            parts.append(f"错误: {len(errors)} 项")
            for e in errors[:3]:
                parts.append(f"  - {e}")
        if warnings:
            parts.append(f"警告: {len(warnings)} 项")
        if ops:
            parts.append(f"检测到操作: {', '.join(ops[:8])}")
        if entries:
            parts.append(f"入口函数: {', '.join(entries)}")
        else:
            parts.append("未定义 apply() 入口函数")

        return "\n".join(parts)


class _ASTCollector(ast.NodeVisitor):
    """AST 遍历收集器——提取函数调用、导入和函数定义。"""

    def __init__(self):
        self.dangerous_calls: set[str] = set()
        self.imports: set[str] = set()
        self.defined_functions: set[str] = set()
        self.has_module_level_code: bool = False

    def visit_Call(self, node: ast.Call):
        """收集函数调用。"""
        full_name = _get_call_name(node)
        if full_name:
            self.dangerous_calls.add(full_name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        """收集 import xxx 语句。"""
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """收集 from xxx import yyy 语句。"""
        if node.module:
            for alias in node.names:
                self.imports.add(f"{node.module}.{alias.name}")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """收集函数定义。"""
        self.defined_functions.add(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """收集异步函数定义。"""
        self.defined_functions.add(node.name)
        self.generic_visit(node)

    def visit_Module(self, node: ast.Module):
        """检查模块级可执行代码。"""
        for child in node.body:
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef, ast.Import, ast.ImportFrom)):
                # 如果是赋值或表达式，检查是否为常量
                if isinstance(child, ast.Assign):
                    # 简单常量赋值可接受（如 VERSION = "1.0"）
                    if not _is_const_assign(child):
                        self.has_module_level_code = True
                elif isinstance(child, ast.Expr):
                    # 表达式语句（如 print）是可执行代码
                    self.has_module_level_code = True
                else:
                    self.has_module_level_code = True
        self.generic_visit(node)


def _is_const_assign(node: ast.Assign) -> bool:
    """检查赋值语句是否仅包含常量。"""
    for target in node.targets:
        if not isinstance(target, ast.Name):
            return False
        if not target.id.isupper():
            return False
    if not isinstance(node.value, (ast.Constant, ast.List, ast.Dict, ast.Tuple)):
        return False
    return True


def _get_call_name(node: ast.Call) -> str | None:
    """解析函数调用的完整名称。

    支持:
    - func() -> "func"
    - os.path.join() -> "os.path.join"
    - obj.method() -> "obj.method"
    """
    func = node.func

    if isinstance(func, ast.Name):
        return func.id

    if isinstance(func, ast.Attribute):
        parts = []
        current = func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    return None


# ── 便捷函数 ──────────────────────────────────────────────

def validate_patch_code(code: str, patch_id: str = "") -> ValidationResult:
    """快速验证补丁代码（使用默认 PatchValidator）。"""
    validator = PatchValidator()
    return validator.validate(code, patch_id)


def validate_patch_file(filepath: str, patch_id: str = "") -> ValidationResult:
    """验证补丁文件。"""
    if not os.path.exists(filepath):
        return ValidationResult(
            is_valid=False,
            risk_level=RiskLevel.REJECTED.value,
            errors=[f"文件不存在: {filepath}"],
        )
    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
    return validate_patch_code(code, patch_id or os.path.basename(filepath))