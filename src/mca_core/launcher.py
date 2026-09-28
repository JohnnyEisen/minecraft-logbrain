"""应用启动器：负责启动环境和可验证的外部扩展加载。"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import hmac
import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore
    except Exception:
        pass


ALLOWED_PATCH_FILES = {
    "fix_crash.py",
    "hotfix.py",
    "hotfix_*.py",
    "patch_*.py",
}

DANGEROUS_PATTERNS = [
    "eval(",
    "exec(",
    "__import__",
    "compile(",
    "os.system",
    "subprocess.",
    "pty.",
    "tty.",
    "socket.",
    "requests.",
    "urllib3.",
    "open(",
    "file(",
    "write(",
]


def _application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _get_signature_key() -> Optional[bytes]:
    """获取补丁签名密钥。"""
    env_key = os.environ.get("MCA_PATCH_SECRET")
    if env_key:
        return env_key.encode("utf-8")

    key_file = _application_dir() / ".patch_key"
    if key_file.is_file():
        try:
            key = key_file.read_text(encoding="utf-8").strip()
        except OSError:
            key = ""
        if key:
            return key.encode("utf-8")

    print("[Security] 未找到签名密钥。请设置环境变量 MCA_PATCH_SECRET 或创建 .patch_key 文件。")
    print("[Security] 未签名补丁将被拒绝加载。")
    return None


def _compute_file_signature(filepath: str, key: bytes) -> Optional[str]:
    """计算文件的 HMAC-SHA256 签名。"""
    try:
        return hmac.new(key, Path(filepath).read_bytes(), hashlib.sha256).hexdigest()
    except FileNotFoundError:
        print(f"[Security] 签名计算失败: 文件不存在 - {filepath}")
    except PermissionError:
        print(f"[Security] 签名计算失败: 权限不足 - {filepath}")
    except OSError as exc:
        print(f"[Security] 签名计算失败: {filepath} - {exc}")
    return None


def _load_approved_signatures() -> set[str]:
    """加载应用目录下的已批准补丁签名。"""
    approved_file = _application_dir() / ".approved_patches"
    if not approved_file.is_file():
        return set()
    try:
        lines = approved_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {line.split()[0] for line in lines if line.strip() and not line.lstrip().startswith("#")}


def _is_safe_patch_file(filepath: str) -> bool:
    """检查补丁文件名、语法和危险代码模式。"""
    filename = Path(filepath).name
    if not any(fnmatch.fnmatch(filename, pattern) for pattern in ALLOWED_PATCH_FILES):
        print(f"[Security] 拒绝加载未授权的补丁文件: {filename}")
        return False

    try:
        content = Path(filepath).read_text(encoding="utf-8")
        ast.parse(content)
    except SyntaxError as exc:
        print(f"[Security] 补丁文件语法错误: {filename} - {exc}")
        return False
    except OSError as exc:
        print(f"[Security] 验证补丁文件失败: {filename} - {exc}")
        return False

    for pattern in DANGEROUS_PATTERNS:
        if pattern in content:
            print(f"[Security] 补丁文件包含危险代码: {filename} - 检测到 {pattern}")
            return False
    return True


def _verify_patch_signature(filepath: str) -> bool:
    """验证补丁文件是否具有已批准的签名。"""
    key = _get_signature_key()
    if key is None:
        print(f"[Security] 签名密钥未配置，拒绝补丁: {Path(filepath).name}")
        return False

    signature = _compute_file_signature(filepath, key)
    if signature in _load_approved_signatures():
        return True

    print(f"[Security] 补丁 {Path(filepath).name} 签名验证失败，未在批准列表中")
    return False


def _load_patches_safely(patch_dir: str) -> None:
    """加载补丁目录中通过安全和签名验证的模块。"""
    patch_path = Path(patch_dir)
    if not patch_path.is_dir():
        return

    loaded_count = 0
    rejected_count = 0
    path_inserted = False
    for file_path in patch_path.iterdir():
        if file_path.suffix != ".py" or not file_path.is_file():
            continue
        if not _is_safe_patch_file(str(file_path)) or not _verify_patch_signature(str(file_path)):
            print(f"[Security] 补丁 {file_path.name} 签名验证失败，已拒绝")
            rejected_count += 1
            continue

        try:
            if not path_inserted:
                sys.path.insert(0, str(patch_path))
                path_inserted = True
            module_name = file_path.stem
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                print(f"[Hotfix] 无法创建模块规格: {file_path.name}")
                rejected_count += 1
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[module_name] = module
            print(f"[Hotfix] 已安全加载补丁: {file_path.name}")
            loaded_count += 1
        except Exception as exc:
            print(f"[Security] 加载补丁失败: {file_path.name} - {exc}")
            rejected_count += 1

    if loaded_count:
        print(f"[Hotfix] 共加载 {loaded_count} 个已签名补丁")
    if rejected_count:
        print(f"[Hotfix] 拒绝了 {rejected_count} 个未签名补丁")


def _validate_lib_directory(lib_dir: str) -> bool:
    """拒绝包含危险 .pth 文件的外部库目录。"""
    lib_path = Path(lib_dir)
    if not lib_path.is_dir():
        return False

    dangerous = ("import ", "exec", "eval", "__import__", "os.system")
    for pth_file in lib_path.glob("*.pth"):
        try:
            content = pth_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if any(pattern in content for pattern in dangerous):
            print(f"[Security] 发现危险的 .pth 文件: {pth_file.name}")
            return False
    return True


def _create_signature_tool() -> None:
    """创建开发者使用的补丁签名工具。"""
    tool_code = '''#!/usr/bin/env python3
"""MCA Brain System 补丁签名工具。"""
import hashlib
import hmac
import os
import sys


def sign_patch(patch_file: str, key: str | None = None) -> None:
    if key is None:
        if not os.path.exists(".patch_key"):
            print("错误: 请提供密钥或创建 .patch_key 文件")
            raise SystemExit(1)
        with open(".patch_key", encoding="utf-8") as file:
            key = file.read().strip()
    with open(patch_file, "rb") as file:
        signature = hmac.new(key.encode("utf-8"), file.read(), hashlib.sha256).hexdigest()
    with open(".approved_patches", "a", encoding="utf-8") as file:
        file.write(signature + "\\n")
    print(f"补丁已签名: {patch_file}")
    print(f"签名: {signature}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python sign_patch.py <补丁文件> [密钥]")
        raise SystemExit(1)
    sign_patch(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
'''
    tool_path = _application_dir() / "tools" / "sign_patch.py"
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(tool_code, encoding="utf-8")
    print(f"[Hotfix] 签名工具已创建: {tool_path}")


def configure_frozen_runtime() -> None:
    """在 PyInstaller 环境中加载已验证的补丁和外部库。"""
    if not getattr(sys, "frozen", False):
        return

    application_path = _application_dir()
    patch_dir = application_path / "patches"
    if patch_dir.exists():
        _load_patches_safely(str(patch_dir))

    lib_dir = application_path / "lib"
    if lib_dir.exists():
        if _validate_lib_directory(str(lib_dir)):
            sys.path.append(str(lib_dir))
            print(f"[Launcher] 已加载外部库目录: {lib_dir}")
        else:
            print("[Security] lib 目录包含危险文件，已拒绝加载")


def launch_app() -> None:
    """初始化应用目录并启动 PyQt6 界面。"""
    configure_frozen_runtime()
    from config.constants import ensure_app_dirs

    ensure_app_dirs()
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        print(
            "[FATAL] PyQt6 is required but not installed. "
            "Run: pip install -e .[desktop]",
            file=sys.stderr,
        )
        raise SystemExit(1)

    from PyQt6.QtWidgets import QApplication
    from mca_core.main_window_pyqt import SiliconeCapsuleApp

    print("[Launcher] Starting Silicone & Capsule UI (PyQt6)...")
    print("[Launcher] High DPI support enabled")
    app = QApplication(sys.argv)
    window = SiliconeCapsuleApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    launch_app()
