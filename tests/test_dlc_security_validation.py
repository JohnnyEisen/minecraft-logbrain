"""VULN-001 修复验证: DLC 文件加载安全验证。"""
import pytest
from pathlib import Path

from brain_system.discovery import _validate_dlc_source


class TestDlcSecurityValidation:
    """DLC 文件安全验证测试"""

    def test_safe_dlc_passes(self):
        """合法的 DLC 代码通过验证。"""
        code = """
class MyDLC:
    def __init__(self):
        self.name = "test"
    def analyze(self, text):
        return len(text)
"""
        ok, err = _validate_dlc_source(code, Path("safe_dlc.py"))
        assert ok, err

    def test_exec_blocked(self):
        """包含 exec() 的 DLC 被拒绝。"""
        code = """
class EvilDLC:
    def __init__(self):
        exec("print('pwned')")
"""
        ok, err = _validate_dlc_source(code, Path("evil_dlc.py"))
        assert not ok
        assert "exec" in err.lower()

    def test_os_system_blocked(self):
        """包含 os.system() 的 DLC 被拒绝。"""
        code = """
import os
class EvilDLC:
    def __init__(self):
        os.system("rm -rf /")
"""
        ok, err = _validate_dlc_source(code, Path("os_dlc.py"))
        assert not ok
        assert "os.system" in err

    def test_subprocess_blocked(self):
        """包含 subprocess.run() 的 DLC 被拒绝。"""
        code = """
import subprocess
class EvilDLC:
    def __init__(self):
        subprocess.run(["evil"])
"""
        ok, err = _validate_dlc_source(code, Path("subprocess_dlc.py"))
        assert not ok
        assert "subprocess" in err.lower()

    def test_socket_blocked(self):
        """包含 socket 导入的 DLC 被拒绝。"""
        code = """
import socket
class EvilDLC:
    def __init__(self):
        s = socket.socket()
"""
        ok, err = _validate_dlc_source(code, Path("socket_dlc.py"))
        assert not ok
        assert "socket" in err.lower()

    def test_ctypes_blocked(self):
        """包含 ctypes 导入的 DLC 被拒绝。"""
        code = """
import ctypes
class EvilDLC:
    def __init__(self):
        ctypes.CDLL("evil.so")
"""
        ok, err = _validate_dlc_source(code, Path("ctypes_dlc.py"))
        assert not ok
        assert "ctypes" in err.lower()

    def test_safe_imports_allowed(self):
        """安全模块（math, json, dataclasses）的 DLC 通过验证。"""
        code = """
import math
import json
from dataclasses import dataclass

@dataclass
class SafeDLC:
    value: float = 0.0

    def __init__(self):
        self.value = math.pi
"""
        ok, err = _validate_dlc_source(code, Path("safe_imports_dlc.py"))
        assert ok, f"Safe imports should be allowed: {err}"

    def test_syntax_error_rejected(self):
        """语法的 DLC 被拒绝。"""
        code = "class BadDLC: pass invalid syntax here"
        ok, err = _validate_dlc_source(code, Path("syntax_err.py"))
        assert not ok
        assert "语法错误" in err

    def test_oversized_dlc_rejected(self):
        """超大的 DLC 文件被拒绝（>512KB）。"""
        code = "# padding\n" * 100000  # ~1.1MB
        # 限制 test 大小以免实际内存爆炸
        code = "# " + "x" * 600000
        ok, err = _validate_dlc_source(code, Path("oversized.py"))
        assert not ok
        assert "过大" in err

    def test_empty_ast_body_allowed(self):
        """只定义空类（无危险调用）的 DLC 通过。"""
        code = "class PlaceholderDLC:\n    pass\n"
        ok, err = _validate_dlc_source(code, Path("empty.py"))
        assert ok, err
