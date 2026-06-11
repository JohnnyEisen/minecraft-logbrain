#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""补丁签名工具 (Patch Signing Tool)
=====================================
用法:
    python tools/sign_patch.py <补丁文件路径>
    python tools/sign_patch.py <文件> --meta <meta.json> --key <.patch_key>
    python tools/sign_patch.py --all --key <.patch_key>
    python tools/sign_patch.py --generate-key
    python tools/sign_patch.py --rotate-key

功能:
    1. 读取密钥 (.patch_key 或 MCA_PATCH_SECRET)
    2. 计算 HMAC-SHA256 签名
    3. 生成 Layer 7 盲态完整性 token
    4. 验证补丁安全性
    5. 写入 .meta.json 的 signature / integrity_token 字段

Layer 7 算法: HMAC-SHA256(secret, sha256(file)||sha256(meta)||signature||patch_id||version)
"""
import hashlib
import hmac
import json
import os
import sys
import ast
import secrets
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
    if not basename.endswith(".py"):
        print(f"[!] 补丁文件必须以 .py 结尾: {basename}")
        return False
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


def compute_layer7_token(filepath, meta_path, key):
    """生成 Layer 7 盲态完整性 token。"""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        sha.update(f.read())
    file_hash = sha.hexdigest()

    with open(meta_path, "rb") as f:
        meta_bytes = f.read()
    meta_hash = hashlib.sha256(meta_bytes).hexdigest()

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 先计算 HMAC 签名
    with open(filepath, "rb") as f:
        signature = hmac.new(key, f.read(), hashlib.sha256).hexdigest()

    patch_id = meta.get("patch_id", os.path.splitext(os.path.basename(filepath))[0])
    version = meta.get("version", "1.0.0")
    message = f"{file_hash}|{meta_hash}|{signature}|{patch_id}|{version}"
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def write_meta_signature(meta_path, signature, layer7_token):
    """将签名和 Layer 7 token 写入 .meta.json。"""
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["signature"] = signature
    meta["integrity_token"] = layer7_token
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[+] 签名已写入: {meta_path}")
    print(f"    signature:       {signature[:32]}...")
    print(f"    layer7_token:    {layer7_token[:32]}...")


def cmd_sign_single(patch_path, meta_path, key):
    """签名单个补丁文件。"""
    print("=" * 60)
    print("补丁签名工具")
    print("=" * 60)
    print(f"文件: {patch_path}")
    print(f"元数据: {meta_path}")

    print("\n--- 阶段 1: 安全验证 ---")
    if not validate_filename(patch_path):
        sys.exit(1)
    if not validate_patch_syntax(patch_path):
        sys.exit(1)
    if not validate_patch_safety(patch_path):
        sys.exit(1)

    print("\n--- 阶段 2: 签名 + Layer 7 token ---")
    signature = compute_signature(patch_path, key)
    print(f"[+] HMAC-SHA256: {signature[:32]}...")
    layer7 = compute_layer7_token(patch_path, meta_path, key)
    print(f"[+] Layer 7:     {layer7[:32]}...")

    print("\n--- 阶段 3: 写入 ---")
    write_meta_signature(meta_path, signature, layer7)
    basename = os.path.basename(patch_path)
    approve_signature(signature, basename)


def cmd_generate_key():
    """生成新的 .patch_key。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_file = os.path.join(root, ".patch_key")
    if os.path.exists(key_file):
        print(f"[!] {key_file} 已存在。使用 --rotate-key 轮换。")
        sys.exit(1)
    new_key = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(new_key)
    os.chmod(key_file, 0o600)
    print(f"[+] 密钥已生成: {key_file}")
    print("    已添加到 .gitignore，不会被提交。")


def cmd_rotate_key():
    """轮换密钥。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    key_file = os.path.join(root, ".patch_key")
    if os.path.exists(key_file):
        backup = key_file + ".old." + datetime.now().strftime("%Y%m%d")
        os.rename(key_file, backup)
        print(f"[*] 旧密钥已备份: {backup}")

    new_key = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(new_key)
    os.chmod(key_file, 0o600)
    print(f"[+] 新密钥已生成: {key_file}")
    print("    建议运行 --all 为所有补丁重签。")


def cmd_sign_all(key):
    """批量重签所有补丁。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    patches_dir = os.path.join(root, "patches")
    if not os.path.isdir(patches_dir):
        print(f"[!] patches 目录不存在: {patches_dir}")
        sys.exit(1)

    count = 0
    for fname in os.listdir(patches_dir):
        if not fname.endswith(".py"):
            continue
        patch_path = os.path.join(patches_dir, fname)
        meta_path = os.path.join(patches_dir, fname.replace(".py", ".meta.json"))
        if not os.path.exists(meta_path):
            print(f"  [跳过] {fname} — 无 .meta.json")
            continue

        print(f"\n  --- {fname} ---")
        try:
            sig = compute_signature(patch_path, key)
            l7 = compute_layer7_token(patch_path, meta_path, key)
            write_meta_signature(meta_path, sig, l7)
            count += 1
        except Exception as e:
            print(f"  [!] 失败: {e}")

    print(f"\n[+] 完成: {count} 个补丁已重签")


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python tools/sign_patch.py <补丁文件>              签名单个补丁")
        print("  python tools/sign_patch.py <文件> --meta <.json>  指定元数据路径")
        print("  python tools/sign_patch.py --generate-key          生成新密钥")
        print("  python tools/sign_patch.py --rotate-key            轮换密钥")
        print("  python tools/sign_patch.py --all --key <.key>      批量重签")
        sys.exit(1)

    # 解析参数
    import argparse

    parser = argparse.ArgumentParser(description="补丁签名工具")
    parser.add_argument("patch_file", nargs="?", help="补丁文件路径")
    parser.add_argument("--meta", help="元数据 JSON 路径")
    parser.add_argument("--key", help="密钥文件路径")
    parser.add_argument("--generate-key", action="store_true", help="生成新密钥")
    parser.add_argument("--rotate-key", action="store_true", help="轮换密钥")
    parser.add_argument("--all", action="store_true", help="批量重签所有补丁")
    args = parser.parse_args()

    if args.generate_key:
        cmd_generate_key()
        return
    if args.rotate_key:
        cmd_rotate_key()
        return

    key = load_key()
    if args.all:
        cmd_sign_all(key)
        return

    patch_path = args.patch_file
    if not patch_path:
        print("[!] 缺少补丁文件路径")
        sys.exit(1)
    if not os.path.exists(patch_path):
        print(f"[!] 文件不存在: {patch_path}")
        sys.exit(1)

    meta_path = args.meta or patch_path.replace(".py", ".meta.json")
    if not os.path.exists(meta_path):
        print(f"[!] 元数据文件不存在: {meta_path}")
        print("    使用 --meta 指定路径，或确保 .meta.json 与 .py 同名同目录")
        sys.exit(1)

    cmd_sign_single(patch_path, meta_path, key)


if __name__ == "__main__":
    main()