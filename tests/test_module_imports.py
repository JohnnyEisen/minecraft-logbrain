import os
import sys
import unittest
import traceback
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KNOWN_OPTIONAL_DEPENDENCIES = {
    "torch", "transformers", "psutil", "GPUtil", "numpy",
    "PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui",
    "sv_ttk", "tkinter", "matplotlib", "PIL", "cryptography",
}

def _module_needs_optional_dep(module_path: str) -> bool:
    modules_that_need_optional = {
        "dlcs",
        "dlcs.brain_dlc_codebert",
        "dlcs.brain_dlc_nn",
        "dlcs.brain_dlc_workflow",
        "dlcs.brain_dlc_hardware",
        "dlcs.brain_dlc_distributed",
        "dlcs.hardware_mhc_config",
        "dlcs.hardware_utils",
        "dlcs.mhc_codebert",
        "dlcs.mhc_config",
        "dlcs.mhc_layer",
        "dlcs.mhc_trainer",
        "dlcs.train_mhc",
        "brain_system.training",
        "brain_system.server",
        "brain_system.ha",
        "mca_core.services.system_service",
        "mca_core.services.auto_test_service",
        "mca_core.services.database",
        "mca_core.exporters",
        "mca_core.prompt_generator",
        "mca_core.main_window_pyqt",
        "mca_core.brain_animation_pyqt",
        "mca_core.screen_adapter_pyqt",
        "mca_core.adaptive_window_manager",
        "mca_core.window_constants",
        "mca_core.window_utils",
        "mca_core.workers_pyqt",
        "brain_system.__main__",
        "brain_system.cli",
        "brain_system.observability",
        "config.app_config",
    }
    return module_path in modules_that_need_optional


def _collect_modules() -> list[tuple[str, Path]]:
    modules = []
    for py_file in SRC_DIR.rglob("*.py"):
        if py_file.name.startswith("_"):
            if py_file.name not in ("__init__.py", "__main__.py"):
                continue
        rel = py_file.relative_to(SRC_DIR)
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        module_name = ".".join(parts)
        if not module_name:
            continue
        modules.append((module_name, py_file))
    return sorted(modules, key=lambda x: x[0])


class TestModuleImports(unittest.TestCase):
    """验证 src/ 下所有 Python 模块均可被导入，捕获类似 diagnostic_engine.py 缺少 Optional 的 bug。"""

    @classmethod
    def setUpClass(cls):
        cls._modules = _collect_modules()

    def test_all_modules_importable(self):
        """所有非可选依赖模块必须可以导入。"""
        failed = []
        skipped = []
        passed = []

        for module_name, file_path in self._modules:
            if _module_needs_optional_dep(module_name):
                skipped.append(module_name)
                continue

            with self.subTest(module=module_name):
                try:
                    exec(f"import {module_name}", globals())
                    passed.append(module_name)
                except Exception as e:
                    tb = traceback.format_exc()
                    failed.append((module_name, file_path, str(e), tb))

        if failed:
            msg_parts = [f"\n{'='*60}"]
            msg_parts.append(f"导入失败: {len(failed)} 个模块\n")
            for mod, fp, err, _ in failed:
                msg_parts.append(f"  {mod}")
                msg_parts.append(f"    路径: {fp}")
                msg_parts.append(f"    错误: {err}")
                msg_parts.append("")
            self.fail("\n".join(msg_parts))

    def test_minimum_coverage(self):
        """至少应有 60% 的模块通过导入测试。"""
        passed = 0
        failed = 0
        for module_name, _ in self._modules:
            if _module_needs_optional_dep(module_name):
                continue
            try:
                exec(f"import {module_name}", globals())
                passed += 1
            except Exception:
                failed += 1

        total = passed + failed
        if total == 0:
            self.fail("没有模块被测试到")
        rate = passed / total
        self.assertGreaterEqual(rate, 0.6, f"导入通过率 {rate:.1%} 低于 60%")

    def test_diagnostic_engine_imports(self):
        """确认 diagnostic_engine.py 可以正确导入。"""
        from mca_core.diagnostic_engine import DiagnosticEngine
        self.assertIsNotNone(DiagnosticEngine)

    def test_learning_imports(self):
        """确认 learning.py 可以正确导入。"""
        from mca_core.learning import CrashPatternLearner
        self.assertIsNotNone(CrashPatternLearner)

    def test_animation_controller_imports(self):
        """确认 animation_controller.py 可以正确导入。"""
        from mca_core.animation_controller import (
            StatusColors, AnimationStateMachine, AnimationType, detect_gpu
        )
        self.assertIsNotNone(StatusColors)
        self.assertIsNotNone(AnimationStateMachine)
        self.assertIsNotNone(AnimationType)
        self.assertIsNotNone(detect_gpu)


if __name__ == "__main__":
    unittest.main()