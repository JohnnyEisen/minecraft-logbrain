#!/usr/bin/env python3
"""版本号一致性校验脚本。

用法:
    python tools/check_version.py              # 检查一致性
    python tools/check_version.py --set 2.1.0  # 统一设为指定版本

架构:
    版本号的唯一真源: src/brain_system/__init__.py → __version__
    ├── src/__init__.py             → from brain_system import __version__ (运行时重导出)
    ├── src/brain_system/core.py    → from brain_system import __version__ (BrainCore.version)
    └── pyproject.toml              → dynamic version {attr = "brain_system.__version__"}

    修改版本号只需编辑 brain_system/__init__.py 中的 __version__ 一行。
    所有其他文件自动同步，无需手动更新。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

VERSION_RE = re.compile(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"', re.MULTILINE)

IMPORT_VERSION_RE = re.compile(
    r"from\s+brain_system\s+import\s+__version__"
)

HARDCODED_VERSION_RE = re.compile(
    r'(?<!\w)(?:version\s*=\s*|__version__\s*=\s*)"(\d+\.\d+\.\d+)"'
)

SETUPTOOLS_ATTR_RE = re.compile(
    r'version\s*=\s*\{attr\s*=\s*"brain_system\.__version__"\}'
)


def _read_canonical() -> str | None:
    source = SRC_DIR / "brain_system" / "__init__.py"
    content = source.read_text(encoding="utf-8")
    match = VERSION_RE.search(content)
    return match.group(1) if match else None


def check_consistency() -> bool:
    canonical = _read_canonical()
    if canonical is None:
        print("[FAIL] 唯一真源 (brain_system/__init__.py) 中未找到 __version__")
        return False

    print(f"[INFO] 唯一真源版本: {canonical}")
    print()

    all_ok = True

    source = SRC_DIR / "brain_system" / "__init__.py"
    print(f"[ OK ] {source.relative_to(PROJECT_ROOT)}  (唯一真源)")

    init_file = SRC_DIR / "__init__.py"
    content = init_file.read_text(encoding="utf-8")
    if IMPORT_VERSION_RE.search(content):
        print(f"[ OK ] {init_file.relative_to(PROJECT_ROOT)}  (from brain_system import __version__)")
    else:
        print(f"[FAIL] {init_file.relative_to(PROJECT_ROOT)}  (缺少 from brain_system import __version__)")
        all_ok = False

    core_file = SRC_DIR / "brain_system" / "core.py"
    content = core_file.read_text(encoding="utf-8")
    if IMPORT_VERSION_RE.search(content) and "self.version = __version__" in content:
        print(f"[ OK ] {core_file.relative_to(PROJECT_ROOT)}  (from brain_system import __version__)")
    else:
        print(f"[FAIL] {core_file.relative_to(PROJECT_ROOT)}  (应通过导入引用版本号)")
        all_ok = False

    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    if SETUPTOOLS_ATTR_RE.search(content) and 'dynamic = ["version"]' in content:
        print(f"[ OK ] {pyproject.relative_to(PROJECT_ROOT)}  (dynamic attr)")
    else:
        print(f"[FAIL] {pyproject.relative_to(PROJECT_ROOT)}  (应使用 setuptools dynamic attr)")
        all_ok = False

    print()
    print("[INFO] 运行时验证...")
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; sys.path.insert(0, 'src'); "
            "from brain_system import __version__ as v1; "
            "from brain_system.core import BrainCore; "
            f"b = BrainCore(); print(v1, b.version)"
        ],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) >= 2 and parts[0] == parts[1] == canonical:
            print(f"  [ OK ] brain_system.__version__ == BrainCore.version == {canonical}")
        else:
            print(f"  [FAIL] 运行时版本不一致: {result.stdout.strip()}")
            all_ok = False
    else:
        print(f"  [FAIL] 运行时导入失败:\n{result.stderr}")
        all_ok = False

    print()

    if all_ok:
        print(f"[PASS] 全部文件版本一致: {canonical}")
    else:
        print(f"[FAIL] 版本不一致，请在 brain_system/__init__.py 中统一修改。")
    return all_ok


def set_version(new_version: str) -> bool:
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        print(f"[FAIL] 无效版本号: {new_version} (需为 MAJOR.MINOR.PATCH)")
        return False

    source_file = SRC_DIR / "brain_system" / "__init__.py"
    content = source_file.read_text(encoding="utf-8")

    match = VERSION_RE.search(content)
    if match is None:
        print("[FAIL] brain_system/__init__.py 中未找到 __version__")
        return False

    old_version = match.group(1)
    new_content = VERSION_RE.sub(
        f'__version__ = "{new_version}"',
        content,
        count=1,
    )
    source_file.write_text(new_content, encoding="utf-8")
    print(f"[INFO] brain_system/__init__.py: {old_version} → {new_version}")
    print("[INFO] 其他文件通过导入自动同步，无需手动更新。")
    print()

    return check_consistency()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="版本号一致性校验")
    parser.add_argument(
        "--set", metavar="VERSION",
        help="将版本号统一设为指定值 (如 2.1.0)",
    )
    args = parser.parse_args()

    if args.set:
        ok = set_version(args.set)
    else:
        ok = check_consistency()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()