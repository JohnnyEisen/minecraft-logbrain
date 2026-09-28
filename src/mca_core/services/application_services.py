"""桌面应用业务服务组合。

将主窗口需要的文件、日志、硬件和历史记录编排从 Qt 窗口中移出。
服务不依赖 Qt，便于单元测试和后续替换界面层。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from config.constants import CONFIG_FILE
from mca_core.analysis_engine import (
    format_hardware_report,
    load_gpu_rules,
    read_history_csv,
    scan_mods_directory,
    write_dep_csv,
)
from mca_core.archive_utils import cleanup_temp_dir, collect_logs_from_paths
from mca_core.diagnostic_engine import DiagnosticEngine
from mca_core.file_io import read_text_limited
from mca_core.hardware_analysis import analyze_hardware_log
from mca_core.services.config_service import ConfigService
from mca_core.services.log_service import LogService
from mca_core.services.system_service import SystemService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LogLoadResult:
    """一次日志加载操作的结果。"""

    content: str
    primary_path: str
    log_paths: tuple[str, ...]
    skipped: tuple[str, ...]
    temp_dirs: tuple[tuple[str, str], ...]
    direct_count: int
    archive_count: int
    total_size_bytes: int

    @property
    def skipped_message(self) -> str:
        if not self.skipped:
            return ""
        details = "\n".join(f"  - {item}" for item in self.skipped[:5])
        if len(self.skipped) > 5:
            details += f"\n  ... 以及其他 {len(self.skipped) - 5} 条"
        return f"部分文件跳过:\n{details}"


class LogIngestionService:
    """负责日志文件、压缩包和 Mod 目录的输入处理。"""

    def load_paths(self, paths: list[str]) -> LogLoadResult:
        if not paths:
            return LogLoadResult("", "", (), (), (), 0, 0, 0)

        log_paths, skipped, temp_dirs = collect_logs_from_paths(paths)
        all_contents: list[str] = []
        for log_path in log_paths:
            try:
                content = read_text_limited(log_path)
            except Exception as exc:
                logger.warning("读取文件失败: %s: %s", log_path, exc)
                continue
            if content.strip():
                all_contents.append(f"# 文件: {os.path.basename(log_path)}\n\n{content}")

        merged_content = "\n\n" + "=" * 80 + "\n\n".join(all_contents) if all_contents else ""
        archive_dirs = tuple(temp_dir for temp_dir, _ in temp_dirs)
        direct_count = sum(
            1 for log_path in log_paths
            if not any(log_path.startswith(temp_dir) for temp_dir in archive_dirs)
        )
        total_size = sum(len(content.encode("utf-8")) for content in all_contents)

        return LogLoadResult(
            content=merged_content,
            primary_path=log_paths[0] if log_paths else "",
            log_paths=tuple(log_paths),
            skipped=tuple(skipped),
            temp_dirs=tuple(temp_dirs),
            direct_count=direct_count,
            archive_count=len(temp_dirs),
            total_size_bytes=total_size,
        )

    @staticmethod
    def load_file(file_path: str) -> str:
        return read_text_limited(file_path)

    @staticmethod
    def scan_mods(folder_path: str) -> dict[str, set[str]]:
        return scan_mods_directory(folder_path)

    @staticmethod
    def cleanup_temp_dir(temp_dir: str) -> None:
        cleanup_temp_dir(temp_dir)


class HardwareAnalysisService:
    """执行硬件/渲染日志分析并生成展示报告。"""

    def __init__(self, system_service: Optional[SystemService] = None) -> None:
        self._system_service = system_service or SystemService()

    def analyze(
        self,
        log_text: str,
        current_mods: dict[str, set[str]],
        *,
        max_snippets: int = 24,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        try:
            system_info = self._system_service.get_system_info()
        except Exception:
            system_info = {}

        result = analyze_hardware_log(
            log_text,
            current_mods=current_mods,
            system_info=system_info,
            gpu_rules=load_gpu_rules(),
            max_snippets=max_snippets,
        )
        return result, system_info, format_hardware_report(result, system_info)


class HistoryService:
    """读取分析历史文件，不包含 Qt 对话框逻辑。"""

    @staticmethod
    def read_rows(history_file: str) -> list[list[str]]:
        return read_history_csv(history_file)


@dataclass
class ApplicationServices:
    """桌面应用运行时依赖的组合根。"""

    log_service: LogService
    config_service: ConfigService
    diagnostic_engine: DiagnosticEngine
    ingestion: LogIngestionService
    hardware: HardwareAnalysisService
    history: HistoryService

    @classmethod
    def create(cls, root_dir: str, config_file: str = CONFIG_FILE) -> "ApplicationServices":
        data_dir = os.path.join(root_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        system_service = SystemService()
        return cls(
            log_service=LogService(),
            config_service=ConfigService(config_file),
            diagnostic_engine=DiagnosticEngine(data_dir=data_dir),
            ingestion=LogIngestionService(),
            hardware=HardwareAnalysisService(system_service),
            history=HistoryService(),
        )


def export_dependencies(
    path: str,
    dependency_pairs: set[tuple[str, str]],
    mods: dict[str, set[str]],
) -> None:
    """保存 Mod 依赖关系，保留旧的导出函数语义。"""
    write_dep_csv(path, dependency_pairs, mods)
