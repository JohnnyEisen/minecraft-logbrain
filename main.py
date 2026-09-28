"""源码树直接启动入口。

安装后的 `logbrain` 命令和 PyInstaller 均通过 `mca_core.launcher` 启动，
本文件只保留向后兼容的 `main()` 入口和旧版补丁验证函数导出。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mca_core.launcher import (  # noqa: E402
    ALLOWED_PATCH_FILES,
    DANGEROUS_PATTERNS,
    _compute_file_signature,
    _create_signature_tool,
    _get_signature_key,
    _is_safe_patch_file,
    _load_approved_signatures,
    _load_patches_safely,
    _validate_lib_directory,
    _verify_patch_signature,
    launch_app,
)


def main() -> None:
    """启动桌面应用。"""
    launch_app()


if __name__ == "__main__":
    main()