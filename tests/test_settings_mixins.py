"""测试设置混入模块。"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

try:
    import tkinter as tk
    _tk_root = tk.Tk()
    _tk_root.withdraw()
    _tk_root.destroy()
    HAS_TK = True
except (ImportError, tk.TclError):
    HAS_TK = False

sys.modules['mca_core.python_runtime_optimizer'] = MagicMock(
    MODE_DESCRIPTIONS=[("标准", "默认优化"), ("高性能", "高CPU模式")],
    apply_version_specific_optimizations=MagicMock()
)


@pytest.mark.skipif(not HAS_TK, reason="Tkinter not available")
class TestSettingsMixin:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.root = tk.Tk()
        self.root.withdraw()
        from src.mca_core.settings_mixins import SettingsMixin
        self.SettingsMixin = SettingsMixin
        yield
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_create_opt_tab_no_tab(self):
        host = MagicMock()
        host.opt_tab = None
        self.SettingsMixin._create_opt_tab(host)
        host.opt_tab = MagicMock()
        host.opt_tab.winfo_exists.return_value = False
        self.SettingsMixin._create_opt_tab(host)

    def test_create_opt_header(self):
        from tkinter import ttk
        parent = ttk.Frame(self.root)
        host = MagicMock()
        host.opt_desc_text = "Test description"
        self.SettingsMixin._create_opt_header(host, parent)
        children = parent.winfo_children()
        assert len(children) >= 2

    def test_create_opt_modes(self):
        host = MagicMock()
        host.opt_mode_var = tk.StringVar(value="标准")
        parent = MagicMock()
        self.SettingsMixin._create_opt_modes(host, parent)

    def test_on_mode_change(self):
        host = MagicMock()
        host.opt_mode_var = tk.StringVar(value="高性能")
        self.SettingsMixin._on_mode_change(host)
        import mca_core.python_runtime_optimizer as opt
        opt.apply_version_specific_optimizations.assert_called_with("高性能")

    def test_on_mode_change_handles_error(self):
        import mca_core.python_runtime_optimizer as opt
        opt.apply_version_specific_optimizations.side_effect = RuntimeError("boom")
        host = MagicMock()
        host.opt_mode_var = tk.StringVar(value="标准")
        self.SettingsMixin._on_mode_change(host)

    def test_create_opt_status(self):
        host = MagicMock()
        parent = MagicMock()
        self.SettingsMixin._create_opt_status(host, parent)

    def test_create_mode_option(self):
        host = MagicMock()
        host.opt_mode_var = tk.StringVar(value="标准")
        self.SettingsMixin._create_mode_option(host, MagicMock(), "测试", "desc")

    def test_create_opt_tab_full(self):
        host = MagicMock()
        host.opt_desc_text = "test"
        host.opt_mode_var = tk.StringVar(value="标准")
        host.opt_tab = None
        self.SettingsMixin._create_opt_tab(host)