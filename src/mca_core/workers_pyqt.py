"""
MCA Brain System - PyQt6 工作线程模块

提供后台分析、AI初始化、自动化测试等工作线程。
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

if TYPE_CHECKING:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

from mca_core.services.log_service import LogService
from mca_core.task_processor import (
    AnalysisHost,
    bootstrap_semantic_engine,
    ensure_semantic_units,
    run_semantic_analysis as _run_semantic_analysis_core,
    _RE_MOD_JAR,
    _RE_MISSING_MOD,
    _RE_MOD_REQUIRES,
)
PyQtAnalyzerHost = AnalysisHost  # type: ignore[assignment]
from mca_core.diagnostic_engine import DiagnosticEngine
from mca_core.result_ranker import rank_results, format_ranked_output

try:
    from scripts.dev.generate_mc_log import generate_batch
    HAS_LOG_GENERATOR: bool = True
except Exception:
    generate_batch = None
    HAS_LOG_GENERATOR = False

try:
    from brain_system.core import BrainCore
    HAS_BRAIN: bool = True
except ImportError:
    HAS_BRAIN = False
    BrainCore = None


class PyQtAnalyzerHost:
    """
    分析器代理类，提供检测器所需的属性和方法。
    
    该类封装了崩溃日志数据，并提供了检测器所需的标准接口。
    """
    
    crash_log: str
    analysis_results: list[str]
    lock: Any
    mods: dict[str, set]
    dependency_pairs: set[tuple[str, str]]
    cause_counts: Counter
    loader_type: str
    mod_names: dict[str, str]

    def __init__(self, log_text: str) -> None:
        """
        初始化分析器代理。
        
        Args:
            log_text: 崩溃日志文本
        """
        self.crash_log = log_text
        self.analysis_results = []
        self.lock = threading.RLock()
        self.mods = defaultdict(set)
        self.dependency_pairs = set()
        self.cause_counts = Counter()
        self.loader_type = "Unknown"
        self.mod_names = {}

        self._extract_mods()
        self._extract_dependency_pairs()

    def add_cause(self, cause_label: str) -> None:
        """
        添加崩溃原因标签。
        
        Args:
            cause_label: 崩溃原因标签
        """
        with self.lock:
            self.cause_counts[cause_label] += 1

    def _extract_mods(self) -> None:
        """从日志中提取模组信息。"""
        seen = set()
        for m in _RE_MOD_JAR.finditer(self.crash_log):
            raw_id, ver = m.groups()
            modid = re.sub(r"[^A-Za-z0-9_.\-]", "", raw_id).strip()
            if modid and modid not in seen:
                self.mods[modid].add(ver)
                seen.add(f"{modid}:{ver}")

    def _extract_dependency_pairs(self) -> None:
        """从日志中提取依赖关系对。"""
        for m in _RE_MISSING_MOD.finditer(self.crash_log):
            self.dependency_pairs.add((m.group(2), m.group(1)))
        for m in _RE_MOD_REQUIRES.finditer(self.crash_log):
            self.dependency_pairs.add((m.group(1), m.group(2)))


# ============================================================
# 语义分析候选缓存 - Semantic Candidate Cache (class-level)
# ============================================================

_SEMANTIC_CANDIDATES = [
    (
        "渲染管线/覆盖层冲突",
        "日志包含 Render thread、OpenGL/Vulkan、RTSSHooks64.dll 或 nvspcap64.dll，画面卡死或频繁闪色。",
        "先关闭 RTSS、MSI Afterburner、NVIDIA Overlay，再切换渲染后端复测。",
        ["render thread", "opengl", "vulkan", "rtsshooks64.dll", "nvspcap64.dll"],
    ),
    (
        "模组依赖缺失或版本冲突",
        "日志出现 Missing mod、requires、NoSuchMethodError、ClassNotFoundException 等依赖报错。",
        "统一模组与 Loader 版本，优先补齐缺失依赖并清理重复模组。",
        ["missing mod", "requires", "nosuchmethoderror", "classnotfoundexception", "noclassdeffounderror"],
    ),
    (
        "Mixin 注入失败",
        "日志出现 InvalidInjectionException、mixin apply failed、descriptor mismatch 等关键词。",
        "检查目标方法签名与映射版本，移除过期注入描述符。",
        ["invalidinjectionexception", "invalid descriptor on", "mixin apply failed", "descriptor mismatch"],
    ),
    (
        "JNI/显卡驱动级崩溃",
        "日志或 hs_err 包含 EXCEPTION_ACCESS_VIOLATION、native crash、驱动模块。",
        "优先排查本地 DLL 与驱动版本，关闭第三方图形钩子后重测。",
        ["exception_access_violation", "native crash", "hs_err", "jni"],
    ),
    (
        "内存或 JVM 参数问题",
        "日志出现 OutOfMemoryError、GC overhead limit exceeded、Java heap space。",
        "调整 JVM 内存参数，减少高占用模组并检查后台占用。",
        ["outofmemoryerror", "gc overhead", "java heap space", "metaspace"],
    ),
]

# ============================================================
# 工作线程信号类 - Worker Signal Classes
# ============================================================

class WorkerSignals(QObject):
    """分析工作线程的信号定义。"""
    
    finished = pyqtSignal(str, object, object, dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    append_log = pyqtSignal(str)


class AIInitSignals(QObject):
    """AI 初始化工作线程的信号定义。"""
    
    done = pyqtSignal(bool, object)
    progress = pyqtSignal(str)


class AutoTestSignals(QObject):
    """自动化测试工作线程的信号定义。"""
    
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    stats = pyqtSignal(str, str, str)
    analysis_result = pyqtSignal(str, str, dict)
    finished = pyqtSignal()
    error = pyqtSignal(str)


# ============================================================
# 工作线程类 - Worker Thread Classes
# ============================================================

class AIInitWorker(QThread):
    """AI 引擎初始化工作线程（带进度反馈和超时控制）。"""
    
    config_path: Optional[str]
    signals: AIInitSignals
    _timeout_secs: float

    AI_INIT_TIMEOUT = 120.0

    def __init__(self, config_path: Optional[str]) -> None:
        """
        初始化 AI 初始化工作线程。
        
        Args:
            config_path: Brain 配置文件路径
        """
        super().__init__()
        self.config_path = config_path
        self.signals = AIInitSignals()
        self._timeout_secs = self.AI_INIT_TIMEOUT

    def _bootstrap_semantic_engine(self, brain: Any) -> tuple[bool, str]:
        return bootstrap_semantic_engine(brain, progress_callback=self.signals.progress.emit)

    def run(self) -> None:
        """执行 AI 引擎初始化。"""
        if not HAS_BRAIN or BrainCore is None:
            self.signals.done.emit(False, "BrainCore 模块不可用")
            return
        
        t_start = time.time()
        
        def _check_timeout(phase: str) -> bool:
            elapsed = time.time() - t_start
            if elapsed > self._timeout_secs:
                self.signals.done.emit(False, f"初始化超时 ({phase}: {elapsed:.0f}s > {self._timeout_secs}s)")
                return True
            return False
        
        try:
            self.signals.progress.emit("正在创建 BrainCore 实例...")
            brain = BrainCore(config_path=self.config_path)
            
            if _check_timeout("BrainCore 创建"):
                return
            
            self.signals.progress.emit("正在加载硬件加速器 DLC...")
            ok, reason = self._bootstrap_semantic_engine(brain)
            
            if _check_timeout("语义引擎引导"):
                return
            
            if not ok:
                self.signals.done.emit(False, reason)
                return
            
            elapsed = time.time() - t_start
            self.signals.progress.emit(f"初始化完成 (耗时 {elapsed:.1f}s)")
            self.signals.done.emit(True, brain)
        except Exception as e:
            self.signals.done.emit(False, str(e))


class AutoTestWorker(QThread):
    """自动化测试工作线程。"""
    
    output_dir: str
    scenarios: list[str]
    count: int
    cleanup: bool
    run_analysis: bool
    engine: Optional[DiagnosticEngine]
    signals: AutoTestSignals
    _cancel_event: threading.Event

    def __init__(
        self,
        output_dir: str,
        scenarios: list[str],
        count: int,
        cleanup: bool,
        engine: Optional[DiagnosticEngine] = None,
        run_analysis: bool = True
    ) -> None:
        """
        初始化自动化测试工作线程。
        
        Args:
            output_dir: 输出目录
            scenarios: 测试场景列表
            count: 生成数量
            cleanup: 是否清理生成文件
            engine: 诊断引擎实例（用于分析）
            run_analysis: 是否在生成后执行分析，默认 True
        """
        super().__init__()
        self.output_dir = output_dir
        self.scenarios = scenarios
        self.count = count
        self.cleanup = cleanup
        self.engine = engine
        self.run_analysis = run_analysis
        self.signals = AutoTestSignals()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """取消测试。"""
        self._cancel_event.set()

    def run(self) -> None:
        """执行自动化测试。"""
        if not HAS_LOG_GENERATOR or generate_batch is None:
            self.signals.error.emit("未安装日志生成器模块，无法执行自动化测试。")
            self.signals.finished.emit()
            return

        try:
            self.signals.log.emit("开始自动化测试...")
            self.signals.log.emit(f"场景: {', '.join(self.scenarios)}")
            self.signals.log.emit(f"数量: {self.count}")
            self.signals.log.emit(f"分析模式: {'启用' if self.run_analysis else '禁用'}")

            t0 = time.time()
            summary = generate_batch(
                output_dir=self.output_dir,
                target_bytes=2 * 1024 * 1024,
                seed=None,
                scenarios=self.scenarios,
                count=self.count,
                report_path=None,
                progress_cb=None,
                cancel_cb=self._cancel_event.is_set,
            )
            if summary is None:
                summary = []

            gen_time = time.time() - t0
            self.signals.log.emit(f"生成完成，共 {len(summary)} 份日志")

            total = len(summary)
            success_count = 0
            fail_count = 0
            analysis_results: list[dict[str, Any]] = []

            for idx, item in enumerate(summary, start=1):
                if self._cancel_event.is_set():
                    self.signals.log.emit("已请求停止，任务中止。")
                    break
                fp = item.get("file", "")
                scenario = item.get("scenario", "unknown")
                self.signals.log.emit(f"[{idx}/{total}] {os.path.basename(fp)} ({scenario})")
                self.signals.progress.emit(idx, total)

                if self.run_analysis and fp and os.path.exists(fp):
                    try:
                        with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                            log_content = f.read()
                        
                        rule_count = 0
                        detector_hits: list[str] = []
                        rule_types: set[str] = set()
                        detector_types: set[str] = set()
                        
                        if self.engine:
                            engine_results = self.engine.analyze(log_content)
                            for res in engine_results:
                                detector_name = res.get("detector")
                                if detector_name:
                                    detector_hits.append(detector_name)
                                    detector_types.add(detector_name)
                                else:
                                    rtype = res.get("type", res.get("name", "未知"))
                                    rule_count += 1
                                    rule_types.add(rtype)
                        
                        total_hits = rule_count + len(detector_hits)
                        
                        if total_hits > 0:
                            success_count += 1
                            parts: list[str] = []
                            if rule_types:
                                parts.append("规则: " + ", ".join(sorted(rule_types)[:3]))
                            if detector_types:
                                parts.append("检测: " + ", ".join(sorted(detector_types)[:3]))
                            self.signals.log.emit(f"    ✓ 检出({total_hits}项): {' | '.join(parts)}")
                        else:
                            fail_count += 1
                            self.signals.log.emit(f"    ✗ 未检出问题 (预期: {scenario})")
                        
                        analysis_results.append({
                            "file": fp,
                            "scenario": scenario,
                            "found_issues": total_hits > 0,
                            "issue_count": total_hits,
                            "rule_types": sorted(rule_types),
                            "detector_types": sorted(detector_types),
                        })
                        
                        self.signals.analysis_result.emit(fp, scenario, {
                            "found_issues": total_hits > 0,
                            "issue_count": total_hits
                        })
                    except Exception as e:
                        fail_count += 1
                        self.signals.log.emit(f"    ✗ 分析失败: {e}")

            cleanup_msg = "未清理"
            if self.cleanup and summary:
                deleted = 0
                for item in summary:
                    try:
                        fp = item.get("file")
                        if fp and os.path.exists(fp):
                            os.remove(fp)
                            deleted += 1
                    except Exception:
                        pass
                cleanup_msg = f"已清理 {deleted} 个文件"
                self.signals.log.emit(cleanup_msg)

            total_time = time.time() - t0
            stats_msg = f"生成耗时 {gen_time:.2f}s"
            if self.run_analysis:
                stats_msg += f" | 分析: {success_count}成功/{fail_count}失败"
            self.signals.stats.emit(f"{total_time:.2f}s", str(len(summary)), cleanup_msg)
            
            self.signals.log.emit(f"\n{'='*40}")
            self.signals.log.emit(f"测试完成！")
            self.signals.log.emit(f"  生成日志: {len(summary)} 份")
            if self.run_analysis:
                self.signals.log.emit(f"  分析成功: {success_count} 份")
                self.signals.log.emit(f"  分析失败: {fail_count} 份")
                detection_rate = success_count / total * 100 if total > 0 else 0
                self.signals.log.emit(f"  检出率: {detection_rate:.1f}%")
                if analysis_results:
                    from collections import defaultdict
                    scenario_hits = Counter()
                    scenario_rule_types: dict[str, set[str]] = defaultdict(set)
                    scenario_detector_types: dict[str, set[str]] = defaultdict(set)
                    for r in analysis_results:
                        sc = r["scenario"]
                        if r["found_issues"]:
                            scenario_hits[sc] += 1
                        for rt in r.get("rule_types", []):
                            scenario_rule_types[sc].add(rt)
                        for dt in r.get("detector_types", []):
                            scenario_detector_types[sc].add(dt)
                    self.signals.log.emit(f"\n  按场景检出统计:")
                    for sc in sorted(scenario_hits.keys()):
                        sc_total = sum(1 for r in analysis_results if r["scenario"] == sc)
                        parts = []
                        if sc in scenario_rule_types and scenario_rule_types[sc]:
                            parts.append("规则: " + ", ".join(sorted(scenario_rule_types[sc])[:3]))
                        if sc in scenario_detector_types and scenario_detector_types[sc]:
                            parts.append("检测器: " + ", ".join(sorted(scenario_detector_types[sc])[:3]))
                        type_info = " | ".join(parts) if parts else "(统一匹配)"
                        self.signals.log.emit(f"    {sc}: {scenario_hits[sc]}/{sc_total} 检出 → {type_info}")
            self.signals.log.emit(f"  总耗时: {total_time:.2f}s")
            
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class AnalysisWorker(QThread):
    """分析工作线程。"""
    
    engine: DiagnosticEngine
    brain: Any
    log_text: str
    signals: WorkerSignals

    def __init__(
        self,
        engine: DiagnosticEngine,
        brain: Any,
        log_text: str
    ) -> None:
        """
        初始化分析工作线程。
        
        Args:
            engine: 诊断引擎
            brain: BrainCore 实例
            log_text: 日志文本
        """
        super().__init__()
        self.engine = engine
        self.brain = brain
        self.log_text = log_text
        self.signals = WorkerSignals()

    def _ensure_semantic_units(self) -> tuple[Optional[Any], Optional[Any], str]:
        return ensure_semantic_units(self.brain)

    def _run_semantic_analysis(self) -> str:
        return _run_semantic_analysis_core(self.brain, self.log_text)

    def run(self) -> None:
        """执行分析。"""
        try:
            self.signals.progress.emit(10, "初始化分析器环境...")
            host = PyQtAnalyzerHost(self.log_text)

            self.signals.progress.emit(20, "启动诊断引擎...")
            self.signals.append_log.emit(">> 启动 MCA 诊断引擎...")

            # engine.analyze 内部已集成 Detector 系统，传入 host 以回写结果
            results = self.engine.analyze(self.log_text, host)
            output: list[str] = []

            # 正则规则的降级结果（detector 系统不可用时触发）
            regex_results = [r for r in results if not r.get("detector")]
            if regex_results:
                output.append(">> 规则库匹配到已知特征：")
                for res in regex_results:
                    title = res.get("title") or res.get("name") or res.get("type") or "未知"
                    output.append(f"  - {title}")
                    diagnosis = res.get("diagnosis")
                    if isinstance(diagnosis, str) and diagnosis.strip():
                        output.append(f"    诊断: {diagnosis.strip()}")
                    sol = res.get("solution", res.get("solutions", []))
                    if isinstance(sol, list):
                        for s in sol:
                            output.append(f"    修复: {s}")

            self.signals.progress.emit(40, "运行深度检测器...")
            self.signals.append_log.emit(">> 深度检测器 (Detectors) 运行完成。")

            # 检测器已通过 engine.analyze(host=host) 运行完成
            if host.analysis_results:
                self.signals.append_log.emit(">> 正在排序和优先级分析...")
                ranked = rank_results(host.analysis_results)
                formatted = format_ranked_output(ranked)
                output.append(formatted)
            else:
                if not regex_results:
                    output.append("未发现明显问题。")

            self.signals.progress.emit(70, "本地诊断完成，连接智脑系统...")

            if self.brain:
                self.signals.append_log.emit(">> 启动 MCA 智脑 (AI 模型) 深度分析...")
                try:
                    ai_result = self._run_semantic_analysis()
                    output.append("\n" + "=" * 48)
                    output.append("  [智脑辅助分析]")
                    output.append("=" * 48)
                    output.append(ai_result)
                except Exception as ai_e:
                    self.signals.append_log.emit(f">> 智脑分析出现异常: {ai_e}")

            self.signals.progress.emit(100, "分析完成")
            self.signals.finished.emit(
                "\n".join(output),
                host.dependency_pairs,
                host.mods,
                dict(host.cause_counts)
            )

        except Exception as e:
            self.signals.error.emit(f"分析失败: {str(e)}")
