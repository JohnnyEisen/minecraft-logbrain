from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Protocol

from mca_core.pattern_repository import get_repository, PatternRepository
from mca_core.regex_cache import RegexCache

logger = logging.getLogger(__name__)

DETECTOR_TIMEOUT_SECONDS = 15.0
MAX_PARALLEL_WORKERS = 8


class DetectorExecutionStrategy(Protocol):
    """检测器执行策略接口（策略模式）。

    允许通过依赖注入替换不同的执行策略，例如：
        - 线程池并行执行（默认）
        - 串行执行（测试/调试）
        - 分布式执行（DLC 集成）
    """

    def execute(
        self,
        detectors: list[Any],
        crash_log: str,
        context: Any,
        *,
        run_single: Callable[[Any, str, Any], tuple[bool, Optional[str]]],
        notify_progress: Optional[Callable[[float, str], None]] = None,
        detector_timeout: float = DETECTOR_TIMEOUT_SECONDS,
    ) -> list[dict[str, Any]]:
        """执行检测器列表，返回结果。

        Args:
            detectors: 检测器实例列表
            crash_log: 崩溃日志内容
            context: AnalysisContext 实例
            run_single: 单检测器执行函数 (detector, crash_log, context) -> (success, error_msg)
            notify_progress: 进度通知回调 (progress_float, message)
            detector_timeout: 单个检测器超时时间（秒）

        Returns:
            检测结果列表
        """
        ...


class ThreadPoolExecutionStrategy:
    """默认线程池并行执行策略。"""

    def __init__(self, max_workers: int = MAX_PARALLEL_WORKERS):
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None

    def _get_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            from mca_core.threading_utils import ThreadPoolManager
            self._executor = ThreadPoolManager.get_instance().get_pool(
                "diagnostic", max_workers=self._max_workers
            )
        return self._executor

    def execute(
        self,
        detectors: list[Any],
        crash_log: str,
        context: Any,
        *,
        run_single: Callable[[Any, str, Any], tuple[bool, Optional[str]]],
        notify_progress: Optional[Callable[[float, str], None]] = None,
        detector_timeout: float = DETECTOR_TIMEOUT_SECONDS,
    ) -> list[dict[str, Any]]:
        total = len(detectors)
        if total == 0:
            return []

        if notify_progress:
            notify_progress(0.0, f"0/{total} 检测器")

        failed_detectors: list[str] = []
        executor = self._get_executor()
        futures: dict[str, Any] = {}

        for detector in detectors:
            name = detector.get_name()
            futures[name] = executor.submit(run_single, detector, crash_log, context)

        completed = 0
        for name, future in futures.items():
            try:
                success, error_msg = future.result(timeout=detector_timeout)
                if not success and error_msg:
                    failed_detectors.append(f"{name}: {error_msg}")
            except FutureTimeoutError:
                logger.warning(f"Detector {name} timed out after {detector_timeout}s")
                failed_detectors.append(f"{name}: timeout > {detector_timeout}s")
            except Exception as e:
                logger.warning(f"Detector {name} failed: {e}")
                failed_detectors.append(f"{name}: {e}")
            completed += 1
            if notify_progress:
                notify_progress(
                    completed / max(total, 1),
                    f"{completed}/{total} 检测器完成" if completed < total else "分析完成"
                )

        return DiagnosticEngine._convert_context_to_results(context, crash_log)


class DiagnosticEngine:
    """诊断引擎 —— 检测器系统的协调层（DI 集成版）。

    优化特性:
        - 并行执行: ThreadPoolExecutor 并发运行检测器
        - LRU+TTL 缓存: 相同日志 10 分钟内不重复分析
        - 正则预筛: 跳过不可能匹配的检测器
        - 仪表盘集成: 记录每次检测的耗时和结果供实时监控
        - 单检测器超时: 防止慢检测器阻塞整个流程
        - 置信度评分: 按信号强度区分结果重要性
        - 策略模式: 支持自定义检测器执行策略（串行/并行/分布式）

    DI 支持:
        支持通过 DI 注入 ConfigManager / AuditTrail / EventBus，
        实现配置集中管理、操作审计和事件通信。
    """

    def __init__(
        self,
        data_dir: str,
        repo: PatternRepository | None = None,
        *,
        config: Any = None,
        audit: Any = None,
        event_bus: Any = None,
        execution_strategy: DetectorExecutionStrategy | None = None,
    ) -> None:
        self.data_dir = data_dir
        if repo:
            self.repo = repo
        else:
            rules_path = os.path.join(data_dir, "diagnostic_rules.json")
            self.repo = get_repository("json", rules_path)

        self.learning_data_file = os.path.join(data_dir, "learning_data.json")
        self.learning_data = self._load_learning_data()
        self.rules = self._load_rules_safely()

        self._config = config
        self._audit = audit
        self._event_bus = event_bus
        self._execution_strategy = execution_strategy or ThreadPoolExecutionStrategy()

        cache_size = 128
        cache_ttl = 600.0
        if config is not None:
            cache_size = config.get_int("engine.cache_size", 128)
            cache_ttl = config.get_float("engine.cache_ttl", 600.0)

        from mca_core.detectors.cache import DetectorCache
        self._detector_cache = DetectorCache(max_size=cache_size, ttl_seconds=cache_ttl)

        self._use_detector_system = True
        self._detector_registry = None
        self._parallel_executor: Optional[ThreadPoolExecutor] = None

        self._dashboard_controller = None
        self._progress_callback: Optional[Callable[[float, str], None]] = None

    @property
    def detector_timeout(self) -> float:
        if self._config is not None:
            return self._config.get_float("engine.detector_timeout", DETECTOR_TIMEOUT_SECONDS)
        return DETECTOR_TIMEOUT_SECONDS

    @property
    def max_workers(self) -> int:
        if self._config is not None:
            return self._config.get_int("engine.max_workers", MAX_PARALLEL_WORKERS)
        return MAX_PARALLEL_WORKERS

    def set_progress_callback(self, callback: Optional[Callable[[float, str], None]]) -> None:
        self._progress_callback = callback

    def _notify_progress(self, progress: float, message: str) -> None:
        if self._progress_callback:
            try:
                self._progress_callback(progress, message)
            except Exception:
                pass

    def set_dashboard_controller(self, controller: Any) -> None:
        self._dashboard_controller = controller

    def _record_detector_metric(
        self, name: str, response_time_ms: float, success: bool, detected: bool
    ) -> None:
        if self._dashboard_controller is None:
            return
        try:
            self._dashboard_controller.record_detector_run(
                name=name,
                response_time_ms=response_time_ms,
                success=success,
                items_processed=1,
                detected=detected,
            )
        except Exception:
            pass

    def _compute_log_hash(self, crash_log: str) -> str:
        prefix = crash_log[:65536] if len(crash_log) > 65536 else crash_log
        return hashlib.sha256(prefix.encode("utf-8")).hexdigest()

    def _load_rules_safely(self):
        patterns = self.repo.load_all_patterns()
        if not patterns:
            defaults = self._create_default_rules()
            for p in defaults["patterns"]:
                self.repo.save_pattern(p)
            return defaults
        return {"patterns": patterns}

    def _create_default_rules(self):
        return {
            "patterns": [
                {
                    "id": "startup_crash",
                    "name": "启动崩溃",
                    "regex": ["Initialization failed", "Unable to launch",
                              "Exception in thread \"main\""],
                    "diagnosis": "游戏启动失败，通常是核心库缺失或版本不匹配。",
                    "solutions": ["检查Java版本是否符合游戏要求", "验证游戏核心文件完整性"]
                },
                {
                    "id": "rendering_crash",
                    "name": "渲染崩溃",
                    "regex": ["Tessellating block model", "Rendering entity", "OpenGL Error",
                              "Exit code -1073741819", "OpenGL debug message.*ERROR",
                              "GLFW error", "OpenGL error \\d+",
                              "Unable to initialize OpenGL", "render.*failed",
                              "Chunk rendering failed"],
                    "diagnosis": "渲染过程中发生错误，可能是显卡驱动或光影模组冲突。",
                    "solutions": ["更新显卡驱动", "移除光影包",
                                  "检查OptiFine/Sodium等优化模组版本"]
                },
                {
                    "id": "world_loading_crash",
                    "name": "世界加载崩溃",
                    "regex": ["Exception loading blockstate", "Exception ticking world",
                              "Error reading world"],
                    "diagnosis": "加载世界时发生错误，可能是区块损坏或模组实体数据异常。",
                    "solutions": ["尝试使用NBTExplorer修复区块",
                                  "移除最近添加的维度/生物模组"]
                },
                {
                    "id": "entity_update_crash",
                    "name": "实体更新崩溃",
                    "regex": ["Ticking entity", "Entity being ticked"],
                    "diagnosis": "实体更新逻辑错误，通常由特定生物或物品引起。",
                    "solutions": ["使用命令/kill @e[type=...]清除报错实体", "移除相关模组"]
                },
                {
                    "id": "out_of_memory",
                    "name": "内存溢出",
                    "regex": ["OutOfMemoryError", "Java heap space",
                              "GC overhead limit exceeded", "Metaspace",
                              "out of memory", "内存不足"],
                    "diagnosis": "Java 内存不足，可能是分配内存过小或存在内存泄漏。",
                    "solutions": ["增加 JVM 内存分配 (-Xmx 参数)", "检查是否有内存泄漏模组",
                                  "减少模组数量"]
                },
                {
                    "id": "missing_dependency",
                    "name": "依赖缺失",
                    "regex": ["Missing.*dependency", "Missing mod",
                              "requires.*not found", "Could not look up mod dependency",
                              "Requirements.*not met", "Mod resolution failed",
                              "Failed to validate mod dependencies"],
                    "diagnosis": "模组缺少必要的前置模组或依赖库。",
                    "solutions": ["安装缺失的前置模组", "检查模组版本兼容性",
                                  "查看模组说明获取依赖列表"]
                },
                {
                    "id": "mixin_conflict",
                    "name": "Mixin 冲突",
                    "regex": ["Mixin apply failed", "Invalid Mixin configuration",
                              "Mixin transformation", "incompatible mixin",
                              "Mixin.*error", "Critical injection failure",
                              "Compatibility error in Mixin"],
                    "diagnosis": "Mixin 注入冲突，多个模组修改了同一游戏代码。",
                    "solutions": ["检查冲突的模组组合", "更新或降级冲突模组",
                                  "使用 Rubidium/Sodium 替代 OptiFine"]
                },
                {
                    "id": "version_conflict",
                    "name": "版本冲突",
                    "regex": ["Version mismatch", "incompatible with.*version",
                              "Duplicate mod", "Mod.*failed to load correctly",
                              "requires minecraft.*\\+",
                              "Mod incompatible with game version"],
                    "diagnosis": "模组版本与游戏版本或其他模组不兼容。",
                    "solutions": ["检查模组支持的 Minecraft 版本", "更新模组到兼容版本",
                                  "移除重复安装的模组"]
                },
                {
                    "id": "gl_error",
                    "name": "OpenGL 错误",
                    "regex": ["GLFW error", "OpenGL error", "GL_INVALID",
                              "driver does not.*support OpenGL", "buffer state",
                              "render.*failed", "Tesselating.*failed"],
                    "diagnosis": "OpenGL 图形接口错误，通常是显卡驱动问题。",
                    "solutions": ["更新显卡驱动到最新版本", "降低图形设置",
                                  "禁用 VBO 或光影"]
                },
                {
                    "id": "compound_error",
                    "name": "复合错误",
                    "regex": ["Multiple errors detected", "Compound failure",
                              "Cascading error"],
                    "diagnosis": "多个错误同时发生，需要逐个排查。",
                    "solutions": ["查看完整日志定位首要错误", "按优先级修复各个问题"]
                }
            ]
        }

    def _load_learning_data(self) -> dict[str, list[dict[str, str]]]:
        if not os.path.exists(self.learning_data_file):
            return {"user_solutions": []}
        try:
            with open(self.learning_data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"user_solutions": []}

    def _ensure_detector_registry(self):
        if self._detector_registry is None:
            try:
                from mca_core.detectors import DetectorRegistry
                self._detector_registry = DetectorRegistry.get_instance()
            except Exception as e:
                logger.warning(f"Failed to init DetectorRegistry: {e}")
                self._detector_registry = None

    def _get_executor(self) -> ThreadPoolExecutor:
        if self._parallel_executor is None:
            from mca_core.threading_utils import ThreadPoolManager
            self._parallel_executor = ThreadPoolManager.get_instance().get_pool(
                "diagnostic", max_workers=self.max_workers
            )
        return self._parallel_executor

    def _analyze_with_detectors_parallel(
        self, crash_log: str, host: Any = None
    ) -> list[dict[str, Any]]:
        """使用执行策略运行所有检测器。

        委托至 self._execution_strategy，默认使用 ThreadPoolExecutionStrategy。
        """
        if not self._detector_registry:
            return []

        from mca_core.detectors.contracts import AnalysisContext

        context = AnalysisContext(analyzer=host, crash_log=crash_log)
        detectors = self._detector_registry.list()

        return self._execution_strategy.execute(
            detectors=detectors,
            crash_log=crash_log,
            context=context,
            run_single=self._run_single_detector,
            notify_progress=self._notify_progress,
            detector_timeout=self.detector_timeout,
        )

    def _run_single_detector(
        self, detector: Any, crash_log: str, context: Any
    ) -> tuple[bool, Optional[str]]:
        """在独立线程中运行单个检测器，记录指标。"""
        import time as _time
        name = detector.get_name()

        if context.is_skipped(name):
            return True, None

        pre_count = len(context.results)
        start = _time.perf_counter()
        try:
            detector.detect(crash_log, context)
            elapsed_ms = (_time.perf_counter() - start) * 1000.0
            detected = len(context.results) > pre_count
            self._record_detector_metric(name, elapsed_ms, True, detected)
            return True, None
        except Exception as e:
            elapsed_ms = (_time.perf_counter() - start) * 1000.0
            self._record_detector_metric(name, elapsed_ms, False, False)
            return False, str(e)

    @staticmethod
    def _convert_context_to_results(context: Any, crash_log: str = "") -> list[dict[str, Any]]:
        from mca_core.detectors.contracts import DetectionResult
        results: list[dict[str, Any]] = []
        for result in context.results:
            if not isinstance(result, DetectionResult):
                continue
            if not result.message:
                continue
            results.append({
                "type": result.cause_label or result.detector,
                "name": result.message,
                "diagnosis": result.message,
                "solutions": [],
                "detector": result.detector,
                "confidence": result.confidence,
            })
        # BUG-004 修复: 检测器路径也生成 AI prompt，与正则回退路径保持一致
        if results and crash_log:
            try:
                from mca_core.prompt_generator import PromptGenerator
                ai_prompt = PromptGenerator.generate_prompt(crash_log)
                for r in results:
                    if "ai_prompt" not in r:
                        r["ai_prompt"] = ai_prompt
            except Exception:
                pass
        return results

    def _analyze_with_regex(self, crash_log: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        ai_prompt = None
        ai_prompt_generated = False

        def _ensure_ai_prompt() -> Optional[str]:
            nonlocal ai_prompt, ai_prompt_generated
            if ai_prompt_generated:
                return ai_prompt
            ai_prompt_generated = True
            try:
                from mca_core.prompt_generator import PromptGenerator
                ai_prompt = PromptGenerator.generate_prompt(crash_log)
            except Exception:
                ai_prompt = None
            return ai_prompt

        for pattern in self.rules.get("patterns", []):
            matched = False
            for regex in pattern.get("regex", []):
                if RegexCache.search(regex, crash_log, flags=re.IGNORECASE):
                    matched = True
                    break

            if matched:
                results.append({
                    "type": pattern["id"],
                    "name": pattern["name"],
                    "diagnosis": pattern["diagnosis"],
                    "solutions": pattern["solutions"],
                    "confidence": 1.0,
                    "ai_prompt": _ensure_ai_prompt(),
                })

        return results

    def analyze(self, crash_log: str, host: Any = None) -> list[dict[str, Any]]:
        if host is not None:
            return self._analyze_no_cache(crash_log, host)

        log_hash = self._compute_log_hash(crash_log)

        cached = self._detector_cache.get(log_hash)
        if cached is not None:
            logger.debug(f"Cache hit for log {log_hash[:16]}...")
            return cached

        results = self._analyze_no_cache(crash_log, None)

        self._detector_cache.set(log_hash, results)

        return results

    def _analyze_no_cache(self, crash_log: str, host: Any) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        self._notify_progress(0.0, "启动检测...")

        if self._use_detector_system:
            self._ensure_detector_registry()
            try:
                detector_results = self._analyze_with_detectors_parallel(crash_log, host)
                if detector_results:
                    results = detector_results
            except Exception as e:
                logger.warning(f"Detector system failed, fallback to regex: {e}")

        if not results:
            results = self._analyze_with_regex(crash_log)

        self._notify_progress(1.0, "完成")

        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.DIAGNOSTIC_COMPLETE,
                    detail=f"诊断完成，发现 {len(results)} 个问题",
                    component="diagnostic_engine",
                    metadata={"result_count": len(results)},
                )
            except Exception:
                pass

        if self._event_bus is not None:
            try:
                from mca_core.events import AnalysisEvent, EventTypes
                self._event_bus.publish_async(
                    AnalysisEvent(
                        type=EventTypes.ANALYSIS_COMPLETE,
                        payload={"result_count": len(results), "source": "diagnostic_engine"},
                    )
                )
            except Exception:
                pass

        return results

    def learn_solution(self, crash_signature, solution):
        self.learning_data["user_solutions"].append({
            "signature": crash_signature,
            "solution": solution,
            "timestamp": str(datetime.now())
        })
        self._save_learning_data()

    def _save_learning_data(self):
        try:
            with open(self.learning_data_file, "w", encoding="utf-8") as f:
                json.dump(self.learning_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save learning data: {e}")

    def shutdown(self) -> None:
        if self._parallel_executor is not None:
            self._parallel_executor = None
        if self._audit is not None:
            try:
                from mca_core.audit import OperationType as OpT
                self._audit.record(
                    op_type=OpT.SYSTEM_STOP,
                    detail="DiagnosticEngine 已关闭",
                    component="diagnostic_engine",
                )
            except Exception:
                pass

    def get_cache_stats(self) -> dict[str, Any]:
        return {
            "detector_cache_size": self._detector_cache.get_stats().size,
            "detector_cache_hit_rate": self._detector_cache.get_stats().hit_rate,
        }