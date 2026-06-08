"""安全模块加载器 (VULN-002 已修复)。

提供安全的模块加载功能，在 exec_module 之前对 .py 文件进行代码安全验证。
复用 plugins.py 的安全验证基础设施，确保与插件系统一致的防护水平。
"""
from __future__ import annotations
import importlib.util
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)


class ModuleLoader:
    """安全的模块加载器。

    在 exec_module 之前对 Python 文件进行安全验证，
    复用 SecurePluginRegistry 的代码审计基础设施。
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir

    def load_module(self, name: str, path: str):
        """安全加载 Python 模块。

        Args:
            name: 模块名称
            path: .py 文件路径

        Returns:
            加载的模块对象，或 None（如果验证失败）
        """
        if not os.path.exists(path):
            return None

        # VULN-002 修复: 安全验证（仅对 .py 文件）
        if path.endswith('.py') and not self._is_safe_module(path):
            logger.error(f"[Security] 拒绝加载未通过安全验证的模块: {path}")
            return None

        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
        return None

    @staticmethod
    def _is_safe_module(path: str) -> bool:
        """验证 .py 文件是否通过安全审查。

        复用 plugins.py 的安全验证基础设施（白名单 + AST 分析），
        确保模块加载器与插件系统的安全标准一致。

        Args:
            path: .py 文件路径

        Returns:
            True 如果文件通过所有安全检查
        """
        try:
            from mca_core.plugins import _validate_plugin_code, PluginSecurityError
            _validate_plugin_code(path)
            return True
        except PluginSecurityError as e:
            logger.warning(f"[Security] 模块安全验证失败: {os.path.basename(path)} - {e}")
            return False
        except ImportError:
            # plugins.py 不可用时的基础降级验证
            return ModuleLoader._basic_safety_check(path)

    @staticmethod
    def _basic_safety_check(path: str) -> bool:
        """基础安全检查（plugins.py 不可用时的降级方案）。

        Args:
            path: .py 文件路径

        Returns:
            True 如果通过基础检查
        """
        DANGEROUS = {'eval(', 'exec(', '__import__', 'compile(', 'os.system', 'subprocess.'}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            for pattern in DANGEROUS:
                if pattern in content:
                    logger.warning(f"[Security] 在 {os.path.basename(path)} 中检测到危险模式: {pattern}")
                    return False
            return True
        except Exception:
            return False

    def try_import(self, module_path: str, fallback_path: Optional[str] = None):
        try:
            return __import__(module_path, fromlist=["*"])
        except Exception:
            if fallback_path:
                return self.load_module(module_path.split(".")[-1], fallback_path)
            return None
