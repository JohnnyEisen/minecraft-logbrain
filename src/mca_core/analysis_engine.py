import os
import re
import csv
import json
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)

GPU_ISSUES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "gpu_issues.json",
)

_gpu_rules_cache: Optional[dict] = None
_gpu_rules_lock = threading.Lock()
_RE_MOD_JAR = re.compile(r"(?:^|[\/\\])([a-zA-Z0-9_\-]+)-(\d[\w\.\-]+)\.jar")


def load_gpu_rules() -> dict[str, Any]:
    global _gpu_rules_cache
    if _gpu_rules_cache is not None:
        return _gpu_rules_cache
    with _gpu_rules_lock:
        if _gpu_rules_cache is not None:
            return _gpu_rules_cache
        try:
            if os.path.exists(GPU_ISSUES_FILE):
                with open(GPU_ISSUES_FILE, "r", encoding="utf-8") as fp:
                    loaded = json.load(fp)
                    if isinstance(loaded, dict):
                        _gpu_rules_cache = loaded
                        return loaded
        except Exception:
            pass
        _gpu_rules_cache = {}
        return {}


def format_hardware_report(result: dict[str, Any], system_info: dict[str, Any]) -> str:
    risk_map = {
        "HIGH": "高",
        "MEDIUM": "中",
        "LOW": "低",
        "NONE": "无",
    }

    def _fmt_mem_gb(value: Any) -> str:
        try:
            num = int(value)
            if num <= 0:
                return "未知"
            return f"{num / (1024 ** 3):.1f} GB"
        except Exception:
            return "未知"

    report_lines: list[str] = []
    report_lines.append("硬件分析报告")
    report_lines.append("=" * 50)

    if system_info:
        report_lines.append("系统概览:")
        report_lines.append(f"- 平台: {system_info.get('platform', '未知')}")
        report_lines.append(f"- Python: {system_info.get('python', '未知')}")
        report_lines.append(f"- 物理核心: {system_info.get('cpu_count', '未知')}")
        report_lines.append(f"- 总内存: {_fmt_mem_gb(system_info.get('memory_total'))}")

        gpus = system_info.get("gpus")
        if isinstance(gpus, list) and gpus:
            report_lines.append("- GPU:")
            for gpu in gpus:
                if isinstance(gpu, dict):
                    name = gpu.get("name", "Unknown")
                    driver = gpu.get("driver", "Unknown")
                    memory = gpu.get("memoryTotal")
                    memory_txt = f"{memory} MB" if memory is not None else "未知"
                    report_lines.append(f"  * {name} | Driver: {driver} | VRAM: {memory_txt}")

    report_lines.append("")
    report_lines.append("风险评估:")
    report_lines.append(
        f"- 级别: {risk_map.get(result.get('risk_level', ''), '无')} | 分数: {result.get('risk_score', 0)}"
    )

    categories = result.get("categories") or []
    if categories:
        report_lines.append(f"- 命中类型: {', '.join(categories)}")

    issues = result.get("issues") or []
    if issues:
        report_lines.append("")
        report_lines.append("诊断命中:")
        for issue in issues:
            category = issue.get("category", "未分类")
            evidence = issue.get("evidence", "")
            report_lines.append(f"- [{category}] {evidence}")

    render_mods = result.get("render_mods") or []
    if render_mods:
        report_lines.append("")
        report_lines.append("可疑渲染模组:")
        report_lines.append("- " + ", ".join(render_mods))

    suggestions = result.get("suggestions") or []
    if suggestions:
        report_lines.append("")
        report_lines.append("建议动作:")
        for tip in suggestions:
            report_lines.append(f"- {tip}")

    snippets = result.get("snippets") or []
    if snippets:
        report_lines.append("")
        report_lines.append("GL/渲染证据片段:")
        report_lines.extend(snippets)

    if not issues and not snippets:
        report_lines.append("")
        report_lines.append("未发现明显的硬件/渲染异常特征。")

    return "\n".join(report_lines)


def scan_mods_directory(folder_path: str) -> dict[str, set[str]]:
    mods: dict[str, set[str]] = defaultdict(set)
    for root, _, files in os.walk(folder_path):
        for name in files:
            if not name.lower().endswith(".jar"):
                continue
            m = _RE_MOD_JAR.search(name)
            if not m:
                continue
            mods[m.group(1)].add(m.group(2))
    return dict(mods)


def write_dep_csv(path: str, dep_pairs: set[tuple[str, str]], mods: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Source Mod", "Requires Target", "Status"])
        for src, tgt in sorted(dep_pairs):
            status = "Present" if tgt in mods else "Missing"
            writer.writerow([src, tgt, status])


def read_history_csv(path: str) -> list[list[str]]:
    rows: list[list[str]] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 4:
                rows.append(list(row))
    return rows


def build_nx_graph(
    dep_pairs: set[tuple[str, str]],
    layout: str = "spring",
    filter_isolated: bool = True,
) -> tuple[Any, Any]:
    try:
        import networkx as nx
    except ImportError:
        return None, None

    G = nx.DiGraph()
    for src, dst in dep_pairs:
        G.add_edge(src, dst)

    if filter_isolated:
        try:
            isolates = list(nx.isolates(G))
            G.remove_nodes_from(isolates)
        except Exception:
            pass

    if layout == "circular":
        pos = nx.circular_layout(G)
    elif layout == "shell":
        pos = nx.shell_layout(G)
    elif layout == "spectral":
        pos = nx.spectral_layout(G)
    elif layout == "random":
        pos = nx.random_layout(G)
    else:
        pos = nx.spring_layout(G, seed=42)

    return G, pos


def tail_file(
    file_path: str,
    stop_event: threading.Event,
    line_callback: Callable[[str], None],
    poll_interval: float = 0.4,
) -> None:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, 2)
        while not stop_event.is_set():
            line = f.readline()
            if line:
                line_callback(line)
            else:
                time.sleep(poll_interval)


def extract_mods_from_log(log_text: str) -> dict[str, set[str]]:
    mods: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    from mca_core.workers_pyqt import _RE_MOD_JAR as mod_jar_re
    for m in mod_jar_re.finditer(log_text):
        raw_id, ver = m.groups()
        modid = re.sub(r"[^A-Za-z0-9_.\-]", "", raw_id).strip()
        if modid and modid not in seen:
            mods[modid].add(ver)
            seen.add(f"{modid}:{ver}")
    return dict(mods)


@dataclass
class AnalysisState:
    file_path: str = ""
    current_dep_pairs: set[tuple[str, str]] = field(default_factory=set)
    current_mods: dict[str, set] = field(default_factory=dict)
    current_cause_counts: dict[str, int] = field(default_factory=dict)
    tail_running: bool = False
    graph_layout_name: str = "spring"
    filter_isolated_nodes: bool = True
    gl_snippets: list[str] = field(default_factory=list)
    hardware_issues: list[str] = field(default_factory=list)
    brain_ready: bool = False

    def reset(self) -> None:
        self.file_path = ""
        self.current_dep_pairs = set()
        self.current_mods = {}
        self.current_cause_counts = {}
        self.tail_running = False
        self.gl_snippets = []
        self.hardware_issues = []

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "dep_pairs_count": len(self.current_dep_pairs),
            "mods_count": len(self.current_mods),
            "cause_counts": self.current_cause_counts,
            "graph_layout": self.graph_layout_name,
            "filter_isolated": self.filter_isolated_nodes,
            "brain_ready": self.brain_ready,
        }