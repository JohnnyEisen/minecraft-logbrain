"""测试模块加载器。"""
import os
import sys
import tempfile
import pytest
from src.mca_core.module_loader import ModuleLoader


class TestModuleLoader:
    def test_load_module_valid(self):
        code = "value = 42\ndef hello(): return 'world'\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
            f.write(code)
            path = f.name
        try:
            loader = ModuleLoader(os.path.dirname(path))
            mod = loader.load_module("test_mod", path)
            assert mod is not None
            assert mod.value == 42
            assert mod.hello() == "world"
        finally:
            os.unlink(path)
            sys.modules.pop("test_mod", None)

    def test_load_module_not_found(self):
        loader = ModuleLoader("/nonexistent")
        mod = loader.load_module("nope", "/nonexistent/fake.py")
        assert mod is None

    def test_load_module_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            loader = ModuleLoader(os.path.dirname(path))
            mod = loader.load_module("empty_mod", path)
            assert mod is not None
        finally:
            os.unlink(path)
            sys.modules.pop("empty_mod", None)

    def test_load_module_registers_in_sys_modules(self):
        code = "x = 1\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
            f.write(code)
            path = f.name
        try:
            loader = ModuleLoader(os.path.dirname(path))
            loader.load_module("registered_mod", path)
            assert "registered_mod" in sys.modules
        finally:
            os.unlink(path)
            sys.modules.pop("registered_mod", None)

    def test_try_import_builtin(self):
        loader = ModuleLoader(".")
        mod = loader.try_import("os")
        assert mod is not None
        assert mod.__name__ == "os"

    def test_try_import_nonexistent_no_fallback(self):
        loader = ModuleLoader(".")
        mod = loader.try_import("nonexistent_module_xyz_123")
        assert mod is None

    def test_try_import_nonexistent_with_fallback(self):
        code = "FALLBACK = True\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
            f.write(code)
            path = f.name
        try:
            loader = ModuleLoader(os.path.dirname(path))
            mod = loader.try_import("nonexistent_xyz_456", path)
            assert mod is not None
            assert mod.FALLBACK is True
        finally:
            os.unlink(path)
            sys.modules.pop("nonexistent_xyz_456", None)

    def test_try_import_fallback_nonexistent(self):
        loader = ModuleLoader(".")
        mod = loader.try_import("no_module_abc_789", "/nonexistent/fallback.py")
        assert mod is None

    def test_load_module_invalid_syntax(self):
        """VULN-002 修复: 无效 Python 代码被安全验证拦截，返回 None 而非抛出异常"""
        code = "this is invalid python syntax !!!\n"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as f:
            f.write(code)
            path = f.name
        try:
            loader = ModuleLoader(os.path.dirname(path))
            # 安全验证应拒绝加载无效代码，返回 None
            result = loader.load_module("bad_mod", path)
            assert result is None, "安全验证应拦截无效代码"
        finally:
            os.unlink(path)
            sys.modules.pop("bad_mod", None)