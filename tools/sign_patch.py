#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCA 补丁签名工具 (Patch Signing Tool)
=============================================
用法:
    python tools/sign_patch.py <补丁文件路径>

功能:
    1. 读取 .patch_key 中的密钥
    2. 计算补丁文件的 HMAC-SHA256 签名
    3. 验证补丁不包含危险模式
    4. 验证补丁通过 AST 语法检查
    5. 将签名写入 .approved_patches

签名算法: HMAC-SHA256
密钥来源: .patch_key 文件 (优先) 或 MCA_PATCH_SECRET 环境变量
"""
import hashlib
import hmac
import os
import sys
import ast
from datetime import datetime

# 与 main.py 保持一致的 DANGEROUS_PATTERNS
DANGEROUS_PATTERNS = [
    'os.system', 'os.popen', 'subprocess.',
    'exec(', 'eval(', 'compile(',
    '__import__', 'importlib.',
    'open(', 'write(', 'read(',
    'socket.', 'requests.', 'urllib.',
    'pickle.', 'marshal.',
    'ctypes.', 'cffi.',
    'sys.exit', 'sys.path',
    'shutil.rmtree', 'shutil.move',
    'globals(', 'locals(',
]

ALLOWED_PATCH_FILES = [
    'hotfix_',
    'fix_crash',
    'patch_',
]


def load_key():
    """加载签名密钥。"""
    # 方法一: 从 .patch_key 文件 (项目根目录)
    key_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.patch_key')
    if os.path.exists(key_file):
        with open(key_file, 'r', encoding='utf-8') as f:
            key = f.read().strip()
        if key:
            print(f"[*] 从 .patch_key 加载密钥: {key_file}")
            return key.encode('utf-8')

    # 方法二: 从环境变量
    env_key = os.environ.get('MCA_PATCH_SECRET', '')
    if env_key:
        print(f"[*] 从 MCA_PATCH_SECRET 环境变量加载密钥")
        return env_key.encode('utf-8')

    print("[!] 未找到签名密钥!")
    print("    方法一: 创建 .patch_key 文件并写入密钥")
    print("    方法二: set MCA_PATCH_SECRET=<密钥>")
    sys.exit(1)


def compute_signature(filepath, key):
    """计算文件的 HMAC-SHA256 签名。"""
    with open(filepath, 'rb') as f:
        content = f.read()
    return hmac.new(key, content, hashlib.sha256).hexdigest()


def validate_patch_safety(filepath):
    """验证补丁文件不包含危险模式。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    errors = []
    for pattern in DANGEROUS_PATTERNS:
        if pattern in content:
            errors.append(f"  [FAIL] 检测到危险模式: {pattern}")

    if errors:
        print("[!] 补丁安全验证失败:")
        for err in errors:
            print(err)
        return False

    print("[+] 补丁安全模式验证: 通过")
    return True


def validate_patch_syntax(filepath):
    """验证补丁文件 Python 语法正确。"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    try:
        ast.parse(content)
        print("[+] AST 语法检查: 通过")
        return True
    except SyntaxError as e:
        print(f"[!] AST 语法错误: {e}")
        return False


def validate_filename(filepath):
    """验证补丁文件名符合规范。"""
    basename = os.path.basename(filepath)
    for prefix in ALLOWED_PATCH_FILES:
        if basename.startswith(prefix):
            print(f"[+] 文件名检查: 通过 ({basename})")
            return True
    print(f"[!] 补丁文件名不符合规范: {basename}")
    print(f"    必须以以下前缀之一开头: {ALLOWED_PATCH_FILES}")
    return False


def approve_signature(signature, patch_name):
    """将签名添加到批准列表。"""
    approved_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        '.approved_patches'
    )
    now = datetime.now().isoformat()

    # 读取现有批准列表
    existing = set()
    if os.path.exists(approved_file):
        with open(approved_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and len(line) >= 64:
                    existing.add(line.split()[0] if ' ' in line else line)

    # 去重
    if signature in existing:
        print(f"[*] 签名已存在，无需重复添加: {signature[:16]}...")
        return

    # 追加新签名
    with open(approved_file, 'a', encoding='utf-8') as f:
        f.write(f"{signature}  # {patch_name} @ {now}\n")

    print(f"[+] 签名已批准: {approved_file}")


def main():
    if len(sys.argv) < 2:
        print("用法: python tools/sign_patch.py <补丁文件路径>")
        print("示例: python tools/sign_patch.py patches/hotfix_secure_ops.py")
        sys.exit(1)

    patch_path = sys.argv[1]
    if not os.path.exists(patch_path):
        print(f"[!] 文件不存在: {patch_path}")
        sys.exit(1)

    print("=" * 60)
    print("MCA 补丁签名工具")
    print("=" * 60)
    print(f"补丁文件: {patch_path}")
    print()

    # 阶段 1: 安全验证
    print("--- 阶段 1: 安全验证 ---")
    if not validate_filename(patch_path):
        sys.exit(1)
    if not validate_patch_syntax(patch_path):
        sys.exit(1)
    if not validate_patch_safety(patch_path):
        sys.exit(1)

    # 阶段 2: 签名
    print("\n--- 阶段 2: 签名 ---")
    key = load_key()
    signature = compute_signature(patch_path, key)
    print(f"[+] HMAC-SHA256: {signature[:32]}...")
    print(f"[+] 完整签名: {signature}")

    # 阶段 3: 批准
    print("\n--- 阶段 3: 批准 ---")
    basename = os.path.basename(patch_path)
    approve_signature(signature, basename)

    print()
    print("=" * 60)
    print("签名完成! 补丁可以安全加载。")
    print("=" * 60)


if __name__ == '__main__':
    main()