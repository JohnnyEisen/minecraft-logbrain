import re
import threading
from collections import Counter, defaultdict
from typing import Any, Callable, Optional
from enum import Enum

# ============================================================
# 预编译正则表达式
# ============================================================

_RE_MOD_JAR = re.compile(r"(?:^|[\/\\])([a-zA-Z0-9_\-]+)-(\d[\w\.\-]+)\.jar")
_RE_MISSING_MOD = re.compile(r"Missing mod '([^']+)' needed by '([^']+)'")
_RE_MOD_REQUIRES = re.compile(r"Mod ([^ ]+) requires ([^ \n]+)")
_RE_INVALID_INJECTION = re.compile(r"InvalidInjectionException", re.IGNORECASE)
_RE_INVALID_DESCRIPTOR = re.compile(
    r"Invalid descriptor on\s+([^:\n]+):([^\s\n]+)", re.IGNORECASE
)
_RE_INVALID_DESCRIPTOR_LINE = re.compile(
    r"^.*Invalid descriptor on.*$", re.IGNORECASE | re.MULTILINE
)

# ============================================================
# 语义分析候选缓存 (class-level)
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
# ProgressStage - 进度阶段定义
# ============================================================

class ProgressStage(Enum):
    INIT_HOST = (10, "初始化分析器环境...")
    START_ENGINE = (20, "启动诊断引擎...")
    RUN_DETECTORS = (40, "运行深度检测器...")
    CONNECT_BRAIN = (70, "本地诊断完成，连接智脑系统...")
    FINISHED = (100, "分析完成")

    @property
    def percent(self) -> int:
        return self.value[0]

    @property
    def message(self) -> str:
        return self.value[1]


# ============================================================
# AnalysisHost - 分析器代理（纯 Python，无 Qt 依赖）
# ============================================================

class AnalysisHost:
    crash_log: str
    analysis_results: list
    lock: threading.RLock
    mods: dict[str, set]
    dependency_pairs: set[tuple[str, str]]
    cause_counts: Counter
    loader_type: str
    mod_names: dict[str, str]

    def __init__(self, log_text: str) -> None:
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
        with self.lock:
            self.cause_counts[cause_label] += 1

    def _extract_mods(self) -> None:
        seen = set()
        for m in _RE_MOD_JAR.finditer(self.crash_log):
            raw_id, ver = m.groups()
            modid = re.sub(r"[^A-Za-z0-9_.\-]", "", raw_id).strip()
            if modid and modid not in seen:
                self.mods[modid].add(ver)
                seen.add(f"{modid}:{ver}")

    def _extract_dependency_pairs(self) -> None:
        for m in _RE_MISSING_MOD.finditer(self.crash_log):
            self.dependency_pairs.add((m.group(2), m.group(1)))
        for m in _RE_MOD_REQUIRES.finditer(self.crash_log):
            self.dependency_pairs.add((m.group(1), m.group(2)))


# ============================================================
# 语义分析引擎 (从 workers_pyqt.py 提取)
# ============================================================

def bootstrap_semantic_engine(
    brain: Any,
    progress_callback: Optional[Callable[[str], None]] = None
) -> tuple[bool, str]:
    if not hasattr(brain, "register_dlc"):
        return False, "BrainCore 不支持 DLC 挂载接口"

    def _report(msg: str) -> None:
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    try:
        dlcs = getattr(brain, "dlcs", {})

        if "Hardware Accelerator" not in dlcs:
            _report("正在初始化硬件加速器...")
            from dlcs.brain_dlc_hardware import HardwareAcceleratorDLC
            brain.register_dlc(HardwareAcceleratorDLC(brain))

        if "Semantic Engine (CodeBERT + UDMA)" not in dlcs:
            _report("正在下载/加载语义模型 (all-MiniLM-L6-v2, ~90MB)...")
            from dlcs.brain_dlc_codebert import CodeBertDLC
            brain.register_dlc(CodeBertDLC(brain))

        semantic = getattr(brain, "dlcs", {}).get("Semantic Engine (CodeBERT + UDMA)")
        if semantic is None:
            return False, "语义引擎 DLC 未挂载"

        _report("正在验证模型就绪状态...")
        units = semantic.provide_computational_units()
        checker = units.get("is_ready")
        if not callable(checker):
            return False, "语义引擎缺少就绪检查接口"

        if not bool(checker()):
            return False, "语义模型尚未完成初始化"

        return True, ""
    except Exception as e:
        return False, f"语义模型启动失败: {e}"


def ensure_semantic_units(brain: Any) -> tuple[Optional[Any], Optional[Any], str]:
    if brain is None:
        return None, None, "智脑核心未初始化"

    if hasattr(brain, "get_computational_unit"):
        try:
            encode_text = brain.get_computational_unit("encode_text")
            calculate_similarity = brain.get_computational_unit("calculate_similarity")
            return encode_text, calculate_similarity, ""
        except Exception:
            pass

    if not hasattr(brain, "register_dlc"):
        return None, None, "当前智脑核心不支持 DLC 动态挂载"

    try:
        dlcs = getattr(brain, "dlcs", {})

        if "Hardware Accelerator" not in dlcs:
            from dlcs.brain_dlc_hardware import HardwareAcceleratorDLC
            brain.register_dlc(HardwareAcceleratorDLC(brain))

        if "Semantic Engine (CodeBERT + UDMA)" not in dlcs:
            from dlcs.brain_dlc_codebert import CodeBertDLC
            brain.register_dlc(CodeBertDLC(brain))
    except Exception as e:
        return None, None, f"语义引擎加载失败: {e}"

    if hasattr(brain, "get_computational_unit"):
        try:
            encode_text = brain.get_computational_unit("encode_text")
            calculate_similarity = brain.get_computational_unit("calculate_similarity")
            return encode_text, calculate_similarity, ""
        except Exception as e:
            return None, None, f"语义单元不可用: {e}"

    return None, None, "智脑核心缺少语义计算接口"


def run_semantic_analysis(brain: Any, log_text: str) -> str:
    if brain is None:
        return "MCA 智脑系统未启动。"

    invalid_injection = _RE_INVALID_INJECTION.search(log_text or "")
    if invalid_injection:
        descriptor = _RE_INVALID_DESCRIPTOR.search(log_text or "")

        lines = [
            "强规则命中（高置信度）:",
            "1. Mixin 注入描述符不匹配（InvalidInjectionException）",
        ]

        if descriptor:
            lines.append(f"   关键故障点: {descriptor.group(1)}:{descriptor.group(2)}")
        else:
            evidence = _RE_INVALID_DESCRIPTOR_LINE.search(log_text or "")
            if evidence:
                lines.append(f"   关键证据: {evidence.group(0).strip()}")

        lines.append("   建议: 优先更新或移除该 Mixin 所属模组，并使用与当前 Minecraft/Loader 匹配的构建。")
        lines.append("提示: 已命中明确根因规则，已跳过通用语义候选排序。")
        return "\n".join(lines)

    if hasattr(brain, "analyze"):
        result = brain.analyze(log_text)
        return result if isinstance(result, str) else str(result)

    encode_text, calculate_similarity, reason = ensure_semantic_units(brain)
    if encode_text is None or calculate_similarity is None:
        return f"MCA 智脑系统已加载，但语义模型未就绪。\n原因: {reason}"

    log_vec = encode_text(log_text)
    if not log_vec:
        return "MCA 智脑系统已加载，但语义模型暂未返回有效向量。"

    candidates = _SEMANTIC_CANDIDATES

    log_lower = (log_text or "").lower()
    scored: list[tuple[float, float, str, str, int]] = []
    for title, pattern_text, suggestion, keywords in candidates:
        pattern_vec = encode_text(pattern_text)
        if not pattern_vec:
            continue
        semantic_score = float(calculate_similarity(log_vec, pattern_vec))
        hit_count = sum(1 for kw in keywords if kw in log_lower)
        keyword_score = min(1.0, hit_count / max(1, len(keywords)))
        blended_score = semantic_score * 0.55 + keyword_score * 0.45
        scored.append((blended_score, semantic_score, title, suggestion, hit_count))

    if not scored:
        return "MCA 智脑系统已加载，语义模型可用，但当前日志未匹配到稳定语义候选。"

    scored.sort(key=lambda x: x[0], reverse=True)
    top_matches = scored[:3]

    lines = ["语义匹配候选（CodeBERT）:"]
    for idx, (score, semantic_score, title, suggestion, hit_count) in enumerate(top_matches, start=1):
        lines.append(f"{idx}. {title}（综合分: {score:.3f}，语义相似度: {semantic_score:.3f}，关键词命中: {hit_count}）")
        lines.append(f"   建议: {suggestion}")

    best_score = top_matches[0][0]
    if best_score < 0.25:
        lines.append("提示: 语义匹配置信度较低，建议结合完整崩溃栈与模组列表复核。")
    elif best_score >= 0.45:
        lines.append("提示: 语义匹配置信度较高，可优先按首项建议处理。")

    return "\n".join(lines)


def aggregate_analysis_results(
    engine_results: list[dict],
    detector_results: list,
    ai_result_text: str = "",
    progress_callback: Optional[callable] = None,
) -> tuple[str, set, dict, dict]:
    output: list[str] = []

    if engine_results:
        for res in engine_results:
            title = res.get("title") or res.get("name") or res.get("type") or "未知"
            output.append(f"• 发现问题: {title}")

            diagnosis = res.get("diagnosis")
            if isinstance(diagnosis, str) and diagnosis.strip():
                output.append(f"  - 诊断: {diagnosis.strip()}")

            sol = res.get("solution", res.get("solutions", []))
            if isinstance(sol, list):
                for s in sol:
                    output.append(f"  - {s}")
            else:
                output.append(f"  - {sol}")

    if detector_results:
        for res in detector_results:
            output.append(f"• {res}")

    if not output:
        output.append("本地诊断引擎及深度检测器均未发现明确的崩溃原因。")

    if ai_result_text:
        output.append("\n=== 智脑深度诊断 ===")
        output.append(ai_result_text)

    return "\n".join(output)