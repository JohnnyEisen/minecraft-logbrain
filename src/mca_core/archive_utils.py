"""
日志压缩包提取工具

提供安全的归档文件解压和日志文件发现功能。
支持的格式: zip, tar.gz, tar.bz2, tar.xz, tar, 7z, rar

安全性:
    - 压缩炸弹防护（文件数量/展开比限制）
    - 路径遍历防护（目录穿越攻击）
    - 临时目录自动清理
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
import tarfile
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 安全限制
_MAX_FILES_IN_ARCHIVE = 10000        # 单压缩包最大文件数
_MAX_EXPANSION_RATIO = 50            # 展开比上限（解压后/压缩前）
_MAX_SINGLE_FILE_SIZE = 500 * 1024 * 1024  # 单文件最大 500MB
_MAX_TOTAL_EXTRACTED = 2 * 1024 * 1024 * 1024  # 总提取上限 2GB

# 日志文件扩展名
_LOG_EXTENSIONS = frozenset({".log", ".txt", ".out", ".crash", ".hs_err_pid"})

# 支持的压缩格式
_ARCHIVE_EXTENSIONS = frozenset({
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
    ".tar.xz", ".txz", ".7z", ".rar",
})


@dataclass
class ArchiveResult:
    """压缩包提取结果。"""
    extracted_files: list[str] = field(default_factory=list)
    log_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_extracted_bytes: int = 0


def is_archive_file(path: str) -> bool:
    """判断文件是否为支持的压缩包格式。

    Args:
        path: 文件路径

    Returns:
        是否为压缩包
    """
    name = os.path.basename(path).lower()
    for ext in _ARCHIVE_EXTENSIONS:
        if name.endswith(ext):
            return True
    return False


def is_log_file(path: str) -> bool:
    """判断文件是否为日志文件。

    Args:
        path: 文件路径

    Returns:
        是否为日志文件
    """
    _, ext = os.path.splitext(path)
    return ext.lower() in _LOG_EXTENSIONS or ext == ""


def _is_within_directory(directory: str, target: str) -> bool:
    """安全检查：确保 target 路径位于 directory 内部（防目录遍历）。

    Args:
        directory: 基准目录
        target: 目标路径

    Returns:
        是否安全
    """
    try:
        real_dir = os.path.realpath(directory)
        real_target = os.path.realpath(target)
        common = os.path.commonpath([real_dir, real_target])
        return common == real_dir
    except Exception:
        return False


def _extract_zip(path: str, dest_dir: str) -> ArchiveResult:
    """安全解压 zip 文件。

    Args:
        path: zip 文件路径
        dest_dir: 目标目录

    Returns:
        ArchiveResult 提取结果
    """
    result = ArchiveResult()
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            file_count = len(zf.infolist())
            if file_count > _MAX_FILES_IN_ARCHIVE:
                result.errors.append(f"压缩文件数({file_count})超过上限({_MAX_FILES_IN_ARCHIVE})")
                return result

            # 检查展开比
            archive_size = os.path.getsize(path)
            total_uncompressed = sum(
                info.file_size for info in zf.infolist() if info.file_size > 0
            )
            if archive_size > 0 and total_uncompressed / archive_size > _MAX_EXPANSION_RATIO:
                result.errors.append(
                    f"展开比({total_uncompressed / archive_size:.1f})超过上限({_MAX_EXPANSION_RATIO})"
                )
                return result

            extracted_bytes = 0
            for info in zf.infolist():
                # 跳过目录
                if info.is_dir():
                    continue

                # 安全检查：防止路径遍历
                member_path = os.path.join(dest_dir, info.filename)
                if not _is_within_directory(dest_dir, member_path):
                    result.errors.append(f"路径遍历攻击检测: {info.filename}")
                    continue

                # 大小检查
                if info.file_size > _MAX_SINGLE_FILE_SIZE:
                    continue
                if extracted_bytes + info.file_size > _MAX_TOTAL_EXTRACTED:
                    result.errors.append("提取总大小超过上限")
                    break

                # 确保父目录存在
                os.makedirs(os.path.dirname(member_path), exist_ok=True)

                try:
                    zf.extract(info, dest_dir)
                    # VULN-014 修复: 检查符号链接遍历攻击
                    if os.path.islink(member_path):
                        link_target = os.readlink(member_path)
                        resolved = os.path.realpath(member_path)
                        if not _is_within_directory(dest_dir, resolved):
                            os.unlink(member_path)
                            result.errors.append(f"符号链接遍历攻击: {info.filename}")
                            continue
                    extracted_bytes += info.file_size
                    result.extracted_files.append(member_path)
                except Exception as e:
                    logger.debug(f"提取文件失败: {info.filename}: {e}")

            result.total_extracted_bytes = extracted_bytes
    except zipfile.BadZipFile as e:
        result.errors.append(f"损坏的 ZIP 文件: {e}")
    except Exception as e:
        result.errors.append(f"ZIP 提取错误: {e}")

    return result


def _extract_tar(path: str, dest_dir: str) -> ArchiveResult:
    """安全解压 tar/tar.gz/tar.bz2/tar.xz 文件。

    Args:
        path: tar 文件路径
        dest_dir: 目标目录

    Returns:
        ArchiveResult 提取结果
    """
    result = ArchiveResult()
    try:
        with tarfile.open(path, 'r:*') as tf:
            members = tf.getmembers()
            file_count = len([m for m in members if m.isfile()])
            if file_count > _MAX_FILES_IN_ARCHIVE:
                result.errors.append(f"压缩文件数({file_count})超过上限({_MAX_FILES_IN_ARCHIVE})")
                return result

            # 检查展开比
            archive_size = os.path.getsize(path)
            total_uncompressed = sum(
                m.size for m in members if m.isfile() and m.size > 0
            )
            if archive_size > 0 and total_uncompressed / archive_size > _MAX_EXPANSION_RATIO:
                result.errors.append(
                    f"展开比({total_uncompressed / archive_size:.1f})超过上限({_MAX_EXPANSION_RATIO})"
                )
                return result

            extracted_bytes = 0
            for member in members:
                if not member.isfile():
                    continue

                # 安全检查
                member_path = os.path.join(dest_dir, member.name)
                if not _is_within_directory(dest_dir, member_path):
                    result.errors.append(f"路径遍历攻击检测: {member.name}")
                    continue

                # 大小检查
                if member.size > _MAX_SINGLE_FILE_SIZE:
                    continue
                if extracted_bytes + member.size > _MAX_TOTAL_EXTRACTED:
                    result.errors.append("提取总大小超过上限")
                    break

                os.makedirs(os.path.dirname(member_path), exist_ok=True)

                try:
                    tf.extract(member, dest_dir, filter='data')
                    extracted_bytes += member.size
                    result.extracted_files.append(member_path)
                except Exception as e:
                    logger.debug(f"提取文件失败: {member.name}: {e}")

            result.total_extracted_bytes = extracted_bytes
    except tarfile.TarError as e:
        result.errors.append(f"TAR 提取错误: {e}")
    except Exception as e:
        result.errors.append(f"TAR 提取错误: {e}")

    return result


def _extract_7z(path: str, dest_dir: str) -> ArchiveResult:
    """解压 7z 文件（需要 py7zr 库）。逐文件安全提取。

    Args:
        path: 7z 文件路径
        dest_dir: 目标目录

    Returns:
        ArchiveResult 提取结果
    """
    result = ArchiveResult()
    try:
        import py7zr
    except ImportError:
        result.errors.append("7z 支持需要安装 py7zr: pip install py7zr")
        return result

    try:
        with py7zr.SevenZipFile(path, 'r') as szf:
            file_list = szf.getnames()
            if len(file_list) > _MAX_FILES_IN_ARCHIVE:
                result.errors.append(f"压缩文件数({len(file_list)})超过上限({_MAX_FILES_IN_ARCHIVE})")
                return result

            extracted_bytes = 0
            for filename in file_list:
                # 路径遍历安全检查
                member_path = os.path.join(dest_dir, filename)
                if not _is_within_directory(dest_dir, member_path):
                    result.errors.append(f"路径遍历攻击检测: {filename}")
                    continue

                # 大小检查（7z 中无法预知单文件大小，解压后检查）
                if extracted_bytes > _MAX_TOTAL_EXTRACTED:
                    result.errors.append("提取总大小超过上限")
                    break

                os.makedirs(os.path.dirname(member_path), exist_ok=True)

                try:
                    szf.extract(dest_dir, targets=[filename])
                    # 检查是否解压出符号链接绕过
                    if os.path.islink(member_path):
                        resolved = os.path.realpath(member_path)
                        if not _is_within_directory(dest_dir, resolved):
                            os.unlink(member_path)
                            result.errors.append(f"符号链接遍历攻击: {filename}")
                            continue
                    if os.path.isfile(member_path):
                        size = os.path.getsize(member_path)
                        if size > _MAX_SINGLE_FILE_SIZE:
                            os.remove(member_path)
                            continue
                        extracted_bytes += size
                        result.extracted_files.append(member_path)
                except Exception as e:
                    logger.debug(f"提取文件失败: {filename}: {e}")

            result.total_extracted_bytes = extracted_bytes
    except Exception as e:
        result.errors.append(f"7z 提取错误: {e}")

    return result


def _extract_rar(path: str, dest_dir: str) -> ArchiveResult:
    """解压 rar 文件（需要 rarfile 库或 unrar 工具）。逐文件安全提取。

    Args:
        path: rar 文件路径
        dest_dir: 目标目录

    Returns:
        ArchiveResult 提取结果
    """
    result = ArchiveResult()
    try:
        import rarfile
    except ImportError:
        result.errors.append("RAR 支持需要安装 rarfile: pip install rarfile")
        return result

    try:
        with rarfile.RarFile(path, 'r') as rf:
            info_list = rf.infolist()
            if len(info_list) > _MAX_FILES_IN_ARCHIVE:
                result.errors.append(f"压缩文件数({len(info_list)})超过上限({_MAX_FILES_IN_ARCHIVE})")
                return result

            extracted_bytes = 0
            for info in info_list:
                if info.isdir():
                    continue

                # 路径遍历安全检查
                member_path = os.path.join(dest_dir, info.filename)
                if not _is_within_directory(dest_dir, member_path):
                    result.errors.append(f"路径遍历攻击检测: {info.filename}")
                    continue

                # 大小检查
                if info.file_size > _MAX_SINGLE_FILE_SIZE:
                    continue
                if extracted_bytes + info.file_size > _MAX_TOTAL_EXTRACTED:
                    result.errors.append("提取总大小超过上限")
                    break

                os.makedirs(os.path.dirname(member_path), exist_ok=True)

                try:
                    rf.extract(info, dest_dir)
                    # 检查符号链接遍历攻击
                    if os.path.islink(member_path):
                        resolved = os.path.realpath(member_path)
                        if not _is_within_directory(dest_dir, resolved):
                            os.unlink(member_path)
                            result.errors.append(f"符号链接遍历攻击: {info.filename}")
                            continue
                    extracted_bytes += info.file_size
                    result.extracted_files.append(member_path)
                except Exception as e:
                    logger.debug(f"提取文件失败: {info.filename}: {e}")

            result.total_extracted_bytes = extracted_bytes
    except Exception as e:
        result.errors.append(f"RAR 提取错误: {e}")

    return result


def extract_archive(path: str) -> Optional[tuple[str, ArchiveResult]]:
    """提取压缩包到临时目录。

    自动检测压缩包类型，安全提取到临时目录，
    扫描并归类日志文件。

    Args:
        path: 压缩包文件路径

    Returns:
        (temp_dir, ArchiveResult) 元组，失败返回 None
    """
    if not os.path.isfile(path):
        return None

    name = os.path.basename(path).lower()
    temp_dir = tempfile.mkdtemp(prefix="mca_archive_")

    try:
        if name.endswith(('.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz', '.tar')):
            result = _extract_tar(path, temp_dir)
        elif name.endswith('.zip'):
            result = _extract_zip(path, temp_dir)
        elif name.endswith('.7z'):
            result = _extract_7z(path, temp_dir)
        elif name.endswith('.rar'):
            result = _extract_rar(path, temp_dir)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        if result.errors:
            for err in result.errors:
                logger.warning(f"提取警告 ({os.path.basename(path)}): {err}")

        # 扫描提取的文件，分类日志文件
        result.log_files = []
        for fp in result.extracted_files:
            if is_log_file(fp) and os.path.isfile(fp):
                result.log_files.append(fp)

        # 按文件名排序（latest.log, debug.log 等优先）
        def _sort_key(fp: str) -> tuple:
            name = os.path.basename(fp).lower()
            if name == "latest.log":
                return (0, fp)
            if name == "debug.log":
                return (1, fp)
            if "crash" in name:
                return (2, fp)
            if "hs_err" in name:
                return (3, fp)
            return (4, fp)

        result.log_files.sort(key=_sort_key)

        return temp_dir, result
    except Exception as e:
        logger.error(f"提取压缩包失败: {path}: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


def cleanup_temp_dir(temp_dir: str) -> None:
    """清理临时提取目录。

    Args:
        temp_dir: 临时目录路径
    """
    if temp_dir and os.path.isdir(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.debug(f"清理临时目录失败: {temp_dir}: {e}")


def collect_logs_from_paths(
    paths: list[str],
    cleanup_after: bool = True,
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """从给定的路径列表中收集日志文件。

    处理逻辑：
    1. 如果路径是压缩包 → 解压并找出日志文件
    2. 如果路径是日志文件 → 直接使用
    3. 统计跳过/错误

    Args:
        paths: 文件路径列表
        cleanup_after: 分析完成后是否清理临时文件（暂不清理，由调用方管理）

    Returns:
        (log_paths, skipped_paths, temp_dirs) 元组：
        - log_paths: 收集到的日志文件路径列表
        - skipped_paths: 跳过的路径及其原因
        - temp_dirs: 需要后续清理的临时目录列表 (dir_path, archive_name)
    """
    log_paths: list[str] = []
    skipped_paths: list[str] = []
    temp_dirs: list[tuple[str, str]] = []

    for path in paths:
        path = path.strip()
        if not path or not os.path.exists(path):
            skipped_paths.append(f"文件不存在: {path}")
            continue

        if not os.path.isfile(path):
            skipped_paths.append(f"不是文件: {path}")
            continue

        if is_archive_file(path):
            extracted = extract_archive(path)
            if extracted is None:
                skipped_paths.append(f"无法提取压缩包: {os.path.basename(path)}")
                continue

            temp_dir, result = extracted
            if result.log_files:
                temp_dirs.append((temp_dir, os.path.basename(path)))
                log_paths.extend(result.log_files)
            else:
                skipped_paths.append(
                    f"压缩包中未找到日志文件: {os.path.basename(path)}"
                )
                cleanup_temp_dir(temp_dir)

            # 记录警告
            for err in result.errors:
                skipped_paths.append(
                    f"压缩包 {os.path.basename(path)}: {err}"
                )
        elif is_log_file(path):
            log_paths.append(path)
        else:
            # 可能是不带扩展名的日志文件，也尝试接受
            log_paths.append(path)

    return log_paths, skipped_paths, temp_dirs