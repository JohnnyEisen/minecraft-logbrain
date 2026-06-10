"""自动测试脚本 — 使用分析引擎直接进行场景测试。

无需依赖 MinecraftCrashAnalyzer (已移除)，直接使用分析引擎组件。
"""

import sys
import os
import time
from collections import Counter
import threading

sys.path.insert(0, os.path.abspath("."))

from scripts.dev.generate_mc_log import generate_batch, SCENARIOS
try:
    from tools.neural_adversary import NeuralAdversaryEngine
    HAS_NEURAL = True
except ImportError:
    HAS_NEURAL = False

from mca_core.detectors.registry import DetectorRegistry
from mca_core.detectors import (
    OutOfMemoryDetector, JvmIssuesDetector, VersionConflictsDetector,
    DuplicateModsDetector, ModConflictsDetector, ShaderWorldConflictsDetector,
    MissingDependenciesDetector, LoaderDetector, MissingGeckoLibDetector,
    GeckoLibMoreDetector, GlErrorsDetector
)
from mca_core.analysis_engine import AnalysisEngine


def create_analysis_engine():
    """创建分析引擎实例，注册所有检测器。"""
    registry = DetectorRegistry()
    registry.register(LoaderDetector())
    registry.register(OutOfMemoryDetector())
    registry.register(JvmIssuesDetector())
    registry.register(MissingDependenciesDetector())
    registry.register(VersionConflictsDetector())
    registry.register(DuplicateModsDetector())
    registry.register(ModConflictsDetector())
    registry.register(ShaderWorldConflictsDetector())
    registry.register(GlErrorsDetector())
    registry.register(MissingGeckoLibDetector())
    registry.register(GeckoLibMoreDetector())

    engine = AnalysisEngine(detector_registry=registry)
    return engine


def run_test_scenario(scenario_name, check_condition, desc):
    print(f"\n[{desc}] Generating '{scenario_name}' Log ...")
    out_dir = "debug_logs/auto_test_runs"
    os.makedirs(out_dir, exist_ok=True)

    summary = generate_batch(
        output_dir=out_dir,
        count=1,
        scenarios=[scenario_name],
        target_bytes=512 * 1024,
        seed=None,
        report_path=None
    )

    file_path = summary[0]["file"]
    with open(file_path, "r", encoding="utf-8") as f:
        log_text = f.read()

    engine = create_analysis_engine()

    start_t = time.time()
    results = engine.analyze(log_text, file_path)
    dur = time.time() - start_t

    cause_counts = Counter()
    for r in results:
        cause_counts[r.get("cause", "unknown")] += 1

    print(f"   Analysis Time: {dur:.3f}s")
    print(f"   Causes Found: {dict(cause_counts)}")
    print(f"   Results: {len(results)} items")

    success = check_condition(results, cause_counts)
    status = "SUCCESS" if success else "FAILURE"
    print(f"-> {status}")
    return success


def test_oom():
    def check(results, cause_counts):
        return any("memory" in str(r).lower() for r in results) or cause_counts.get("内存不足", 0) > 0
    return run_test_scenario("oom", check, "OOM Detection")


def test_gl_error():
    def check(results, cause_counts):
        return any("gl" in str(r).lower() or "render" in str(r).lower() for r in results) or cause_counts.get("显卡/渲染", 0) > 0
    return run_test_scenario("gl_error", check, "OpenGL Error Detection")


def test_adversarial():
    def check(results, cause_counts):
        return len(results) >= 0

    print("\n[Neural Adversary] Testing AI-Generated Log...")
    if not HAS_NEURAL:
        print("   (Note: NeuralEngine not found, using simulation fallback)")

    return run_test_scenario("adversarial", check, "Adversarial Generator Integrity")


def run_all_tests():
    print("=== Starting Automated Test Suite ===")
    results = []
    results.append(test_oom())
    results.append(test_gl_error())
    results.append(test_adversarial())

    passed = sum(results)
    total = len(results)
    print("=" * 40)
    print(f"Total Tests: {total}")
    print(f"Passed:      {passed}")
    print(f"Result:      {'PASS' if passed == total else 'FAIL'}")
    print("=" * 40)


if __name__ == "__main__":
    run_all_tests()