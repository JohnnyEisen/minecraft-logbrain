"""
诊断结果优先级排序与格式化模块

解决 MCA 输出噪音和优先级混乱的核心问题：
1. 按严重程度对检测结果排序（致命 > 严重 > 警告 > 提示）
2. 智能去重（相同问题合并显示）
3. 按优先级分层输出，确保用户首先看到最关键的信息
4. 识别 header+子条目+续行结构，完整保留检测器输出语义

输出结构约定（所有检测器都必须遵守）：
- Header   : 普通文本行，标识新的检测结果块
- Sub-item : 以 "  - " 或 "- " 开头的行，属于上方 Header 的详情列表
- Continuation : 以 建议/Suggestion/提示/修复/Fix 等开头的行，
                 延续上方块而非开启新块（防止修复建议被孤儿化）

设计原则：
- 用户最关心的永远是"这个问题会让我无法启动游戏吗？"
- 其次是"我能具体做什么来修复它？"
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# —— 严重程度等级 ——
SEV_CRITICAL = 10   # 致命：直接导致游戏无法启动
SEV_HIGH = 8        # 高：很可能是崩溃根因
SEV_MEDIUM = 5      # 中：有影响但不一定是主因
SEV_LOW = 3         # 低：辅助信息
SEV_INFO = 1        # 提示：仅供参考

# —— 原因分类 → 严重程度映射 ——
CAUSE_SEVERITY: dict[str, int] = {
    "缺失依赖": SEV_CRITICAL,   # 缺失依赖 → 无法启动
    "Mixin冲突": SEV_CRITICAL,   # Mixin 冲突 → 几乎必崩
    "Mixin": SEV_CRITICAL,       # Mixin 相关（别名）
    "内存溢出": SEV_HIGH,        # OOM → 严重崩溃
    "JVM问题": SEV_HIGH,         # JVM 配置 → 常见根因
    "JVM": SEV_HIGH,             # JVM 相关（别名）
    "着色器/世界冲突": SEV_HIGH,  # 世界进不去
    "GPU/OpenGL错误": SEV_HIGH,  # 渲染崩溃
    "GPU": SEV_HIGH,             # GPU 相关（别名）
    "模组冲突": SEV_MEDIUM,       # 模组配置打架
    "重复Mod": SEV_MEDIUM,        # 重复模组
    "版本冲突": SEV_MEDIUM,       # 版本不匹配
    "加载器": SEV_MEDIUM,        # 加载器问题
    "GeckoLib": SEV_MEDIUM,      # GeckoLib 特定问题
    "其他": SEV_LOW,             # 通用
}

# 预计算：按严重度降序排列的标签列表（用于 _extract_cause_label 优先级匹配）
_CAUSE_LABELS_BY_SEVERITY: list[str] = [
    label for label, _ in sorted(CAUSE_SEVERITY.items(), key=lambda x: -x[1])
]

# —— 中文关键词 → 严重程度（fallback，仅当 cause_label 未匹配时使用） ——
CN_CRITICAL_KEYWORDS = frozenset({
    "缺失依赖", "Mixin冲突", "Mixin",
    "MissingModsException", "MissingSources",
})
CN_HIGH_KEYWORDS = frozenset({"内存溢出", "JVM", "GPU", "OpenGL", "着色器", "世界"})
CN_MEDIUM_KEYWORDS = frozenset({"重复Mod", "重复JAR", "版本冲突", "模组冲突"})

# —— 行类型识别 ——
# 规则优先级：
#   1. 缩进行（raw 有前导空白）→ 属于当前块的详情
#   2. 续行（"建议"/"Suggestion" 等）→ 属于当前块
#   3. 其它 → 新 Header
#
# 注意：缩进检测必须在 strip() 之前进行，因为 strip() 会去除前导空白。
#       使用 "raw 是否以 stripped_text 开头" 来判断是否有前导空白。

# 续行（非新 Header）：建议、修复方案等行，应延续上方块而非开启新块
# 防止类似 "建议: 移除冲突的模组版本" 被孤儿化为独立的 SEV_LOW 条目
_CONTINUATION_PATTERN = re.compile(
    r"^(?:建议|Suggestion|提示|修复|🔧|Fix|Repair|Workaround|Note|说明)",
    re.IGNORECASE,
)

# 续行（精确前缀匹配）：更快路径
_CONTINUATION_EXACT = frozenset({
    "Suggestion:",
    "建议：",
    "建议:",
    "提示：",
    "修复方案：",
})

# —— DuplicateMods 检测器的噪音标记 ——
DUPLICATE_JAR_PATTERN = re.compile(r"日志中存在大量重复")

# —— 结构化元数据前缀解析 ——
# analysis_results 条目格式: "[DetectorName] message"
# 注意: 只剥离 [DetectorName] 和紧随的单个空格，保留 message 中的前导空白
# 例如 "[D]   sub" → "  sub"（保留缩进空白以供缩进检测）
_DETECTOR_PREFIX_PATTERN = re.compile(r"^\[([^\]]+)\]\s")


def _strip_detector_prefix(text: str) -> tuple[str, str]:
    """从文本中剥离检测器前缀，返回 (clean_text, detector_name)。

    Args:
        text: 可能包含 "[DetectorName] message" 格式的文本

    Returns:
        (清理后的消息文本, 检测器名称或空字符串)
    """
    m = _DETECTOR_PREFIX_PATTERN.match(text)
    if m:
        return text[m.end():], m.group(1)
    return text, ""


def _extract_cause_label(text: str) -> str:
    """从结果文本中提取原因分类标签。

    按严重度降序匹配，确保高严重度标签优先选择。
    例如同时匹配 "缺失依赖"(CRITICAL) 和 "版本冲突"(MEDIUM) 时选择前者。

    Args:
        text: 单行结果文本（可能含 [DetectorName] 前缀）

    Returns:
        匹配的原因标签，如果没有匹配则返回空字符串
    """
    # 剥离检测器前缀以避免干扰标签匹配
    clean_text, _ = _strip_detector_prefix(text)
    # 按严重度降序匹配 CAUSE_SEVERITY 中的 key
    for label in _CAUSE_LABELS_BY_SEVERITY:
        if label in clean_text:
            return label

    # 特殊处理：DuplicateMods 输出不含 "重复Mod" 但包含 "重复 JAR"
    if "重复 JAR" in clean_text or "重复JAR" in clean_text:
        return "重复Mod"

    return ""


def _is_continuation(text: str) -> bool:
    """判断该行是否为上一块的续行（非新 Header）。

    续行比如 "Suggestion: ..."、"建议：..."、"提示：..." 等，
    它们不应开启新的检测结果块，而应附加到上一个 Header 块中。

    Args:
        text: 已 strip 的单行文本（可能含 [DetectorName] 前缀）

    Returns:
        True 表示该行是续行，应附加到上一块
    """
    # 先剥离检测器前缀
    clean_text, _ = _strip_detector_prefix(text)
    # 精确前缀匹配（更快）
    for prefix in _CONTINUATION_EXACT:
        if clean_text.startswith(prefix):
            return True
    # 正则匹配
    return bool(_CONTINUATION_PATTERN.match(clean_text))


def _classify_severity(text: str, cause_label: str = "") -> int:
    """根据内容自动分类严重程度。

    优先级：cause_label 匹配 → 中文关键词 → 英文关键词 → 默认低优先级
    """
    # 0. 剥离检测器前缀
    clean_text, _ = _strip_detector_prefix(text)

    # 1. 优先使用 cause_label 映射
    if cause_label and cause_label in CAUSE_SEVERITY:
        return CAUSE_SEVERITY[cause_label]

    # 2. 检查中文关键词（检测结果第一行通常包含中文原因分类）
    for kw in CN_CRITICAL_KEYWORDS:
        if kw in clean_text:
            return SEV_CRITICAL
    for kw in CN_HIGH_KEYWORDS:
        if kw in clean_text:
            return SEV_HIGH
    for kw in CN_MEDIUM_KEYWORDS:
        if kw in clean_text:
            return SEV_MEDIUM

    low = clean_text.lower()

    # 3. 英文致命关键词
    critical_keywords = [
        "missingsources", "missingmodsexception", "cannot load",
        "fatal error", "crash report", "unable to",
        "mixin apply failed", "incompatible"
    ]
    for kw in critical_keywords:
        if kw in low:
            return SEV_CRITICAL

    # 4. 英文高危词汇
    high_keywords = [
        "outofmemory", "java heap", "permgen", "metaspace",
        "opengl error", "could not create shader",
        "corrupt", "invalid"
    ]
    for kw in high_keywords:
        if kw in low:
            return SEV_HIGH

    # 5. 英文中危词汇
    # BUG-C07 修复: "warn" 太泛（匹配所有 WARN 行），移除改用更精确词汇
    medium_keywords = [
        "mod conflict", "version mismatch",
        "duplicate", "missing mod", "not found", "deprecated"
    ]
    for kw in medium_keywords:
        if kw in low:
            return SEV_MEDIUM

    return SEV_LOW


@dataclass
class RankedResult:
    """排序后的诊断结果条目。"""
    severity: int
    severity_label: str
    message: str
    raw_message: str
    cause_label: str = ""
    is_noise: bool = False
    detector_name: str = ""


def rank_results(results_raw: list[str]) -> list[RankedResult]:
    """对原始检测结果进行排序和分组。

    规则：
    1. 识别 Header + Sub-item + Continuation 三层结构
       - Sub-item:  "  - xxx" 格式的详情列表
       - Continuation: "建议/Suggestion" 等续行（不开启新块）
    2. 整个块共享 Header 的严重度分类
    3. 合并重复条目（相同 Header 前缀仅保留一条）
    4. 按严重程度排序（致命 → 高 → 中 → 低 → 提示）
    5. 标记和降级扫描器噪音条目

    Args:
        results_raw: host.analysis_results 中的原始字符串列表

    Returns:
        排序后的 RankedResult 列表
    """
    if not results_raw:
        return []

    # —— 第一阶段：将原始行分组为 Header+内容块 ——
    # 每一块: (header, items, cause_label, is_noise, detector_name)
    # 
    # 行分类规则（按优先级）：
    #   1. 缩进行 — 原始字符串在剥离检测器前缀后，clean_text 有前导空白
    #      例: raw="[D]   - subitem", clean_text="  - subitem" → 缩进
    #   2. 续行 — clean_text 以 "建议"/"Suggestion" 等开头
    #   3. 空行 — 跳过
    #   4. 新 Header — 以上都不是
    blocks: list[tuple[str, list[str], str, bool, str]] = []
    current_header = ""
    current_items: list[str] = []
    current_cause = ""
    current_noise = False
    current_detector = ""

    for raw in results_raw:
        text = raw.strip()
        if not text:
            continue

        # 剥离检测器前缀，获取干净的文本
        clean_text, detector = _strip_detector_prefix(text)

        # 缩进行检测：有前导空白（raw 不以 text 开头）或
        # clean_text 有前导空白（检测器前缀后面的空白缩进）
        # 例如: "  - subitem" 或 "[Detector]   - subitem"
        is_indented = (
            not raw.startswith(text)  # raw 有外部前导空白
            or clean_text.startswith((" ", "\t"))  # 前缀后有缩进空白
            or clean_text.startswith("- ")  # 子条目标记
        )
        if is_indented:
            current_items.append(text)
            continue

        # 续行（"建议"/"Suggestion" 等）→ 属于当前块，不开启新块
        if _is_continuation(clean_text):
            current_items.append(text)
            continue

        # 新 Header：保存上一个块（包括空 header 的孤儿子条目块）
        if current_header or current_items:
            blocks.append((current_header, current_items, current_cause, current_noise, current_detector))

        current_header = clean_text if clean_text else text
        current_items = []
        current_cause = _extract_cause_label(text)
        current_noise = bool(DUPLICATE_JAR_PATTERN.search(text))
        current_detector = detector

    # 保存最后一个块
    if current_header or current_items:
        blocks.append((current_header, current_items, current_cause, current_noise, current_detector))

    # —— 第二阶段：构建 RankedResult ——
    ranked: list[RankedResult] = []
    seen_prefixes: dict[str, int] = {}

    for header, items, cause, noise, detector_name in blocks:
        # 组装完整消息
        if not header:
            # 孤儿子条目（没有 header）：仅用子条目内容
            message = "\n".join(items)
            display_header = message[:80]
        else:
            if items:
                message = header + "\n" + "\n".join(items)
            else:
                message = header
            display_header = header

        # 去重
        prefix = display_header[:80]
        if prefix in seen_prefixes:
            continue
        seen_prefixes[prefix] = len(ranked)

        severity = _classify_severity(header if header else message, cause)

        # 噪音条目降级：最高不超过 SEV_MEDIUM
        if noise and severity > SEV_MEDIUM:
            severity = SEV_MEDIUM

        severity_label = {
            SEV_CRITICAL: "FATAL",
            SEV_HIGH: "ERROR",
            SEV_MEDIUM: "WARN",
            SEV_LOW: "INFO",
            SEV_INFO: "HINT",
        }.get(severity, "INFO")

        ranked.append(RankedResult(
            severity=severity,
            severity_label=severity_label,
            message=message,
            raw_message=header if header else message,
            cause_label=cause,
            is_noise=noise,
            detector_name=detector_name,
        ))

    # —— 排序：严重度降序 ——
    ranked.sort(key=lambda r: (-r.severity, seen_prefixes.get(r.raw_message[:80], 0)))

    return ranked


def format_ranked_output(ranked: list[RankedResult]) -> str:
    """将排序后的结果格式化为可读输出。

    输出结构：
    ========================================
    [致命错误] 以下问题可能直接导致游戏崩溃或无法启动
    ----------------------------------------
    检测到可能的缺失依赖的MOD:
    - lunatriuscore
    建议: 安装 lunatriuscore >= 1.2.0.42

    [需要注意] 可能影响但不一定是主因
    ...

    [参考信息]
    ...

    Args:
        ranked: 排序后的结果列表

    Returns:
        格式化的多行字符串
    """
    if not ranked:
        return "未发现明显问题。"

    lines: list[str] = []
    current_sev_level = -1

    sev_headers = {
        SEV_CRITICAL: f"{'=' * 48}\n  [致命错误] 以下问题可能直接导致游戏崩溃或无法启动\n{'=' * 48}",
        SEV_HIGH: f"{'=' * 48}\n  [高危问题] 很可能是崩溃的直接原因\n{'=' * 48}",
        SEV_MEDIUM: f"{'=' * 48}\n  [需要注意] 可能影响但不一定是主因\n{'=' * 48}",
        SEV_LOW: f"{'─' * 48}\n  [参考信息]\n{'─' * 48}",
        SEV_INFO: f"{'─' * 48}\n  [附加提示]\n{'─' * 48}",
    }

    for r in ranked:
        # 计算当前条目所属的分组级别
        if r.severity >= SEV_CRITICAL:
            current_level = SEV_CRITICAL
        elif r.severity >= SEV_HIGH:
            current_level = SEV_HIGH
        elif r.severity >= SEV_MEDIUM:
            current_level = SEV_MEDIUM
        elif r.severity >= SEV_LOW:
            current_level = SEV_LOW
        else:
            current_level = SEV_INFO

        # 分组变化时输出新的分组标题
        if current_level != current_sev_level:
            current_sev_level = current_level
            lines.append("")
            lines.append(sev_headers.get(current_level, ""))

        # 噪音条目标记
        if r.is_noise:
            lines.append(f"\n  [扫描器噪音] {r.message}")
        else:
            for line in r.message.split("\n"):
                # 剥离检测器前缀 "[DetectorName] " 以保持输出整洁
                clean_line, _ = _strip_detector_prefix(line)
                lines.append(f"  {clean_line}")

        lines.append("")

    return "\n".join(lines)