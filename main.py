# ============================================================
# PyQt6 高DPI支持 - 必须在任何导入之前设置
# ============================================================
import os
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'PassThrough'

import sys
import fnmatch
import ast
import hashlib
import hmac
from typing import Optional

# Add src/ to path for new directory structure
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.exists(src_dir):
    sys.path.insert(0, src_dir)

# ============================================================
# V-001 & V-003 Fix: Secure Patch Loader with Signature Verification
# ============================================================

# 获取签名密钥 - 优先级: 环境变量 > 内嵌密钥 > 默认密钥
def _get_signature_key() -> Optional[bytes]:
    """
    获取补丁签名密钥
    优先级: MCA_PATCH_SECRET环境变量 > 内嵌密钥 > 默认密钥
    """
    # 1. 尝试从环境变量获取
    env_key = os.environ.get('MCA_PATCH_SECRET')
    if env_key:
        return env_key.encode('utf-8')
    
    # 2. 尝试从同目录的 .patch_key 文件读取
    app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    key_file = os.path.join(app_dir, '.patch_key')
    if os.path.exists(key_file):
        try:
            with open(key_file, 'r') as f:
                key = f.read().strip()
                if key:
                    return key.encode('utf-8')
        except Exception:
            pass
    
    # 3. VULN-007 修复: 生产环境拒绝默认密钥，必须配置 MCA_PATCH_SECRET
    print("[Security] 未找到签名密钥。请设置环境变量 MCA_PATCH_SECRET 或创建 .patch_key 文件。")
    print("[Security] 未签名补丁将被拒绝加载。")
    return None

def _compute_file_signature(filepath: str, key: bytes) -> Optional[str]:
    """计算文件的 HMAC-SHA256 签名。
    
    H-002 修复: 失败时返回 None 并打印错误，而非返回空字符串
    以防止调用方误判空签名为有效。
    """
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
        signature = hmac.new(key, content, hashlib.sha256).hexdigest()
        return signature
    except FileNotFoundError:
        print(f"[Security] 签名计算失败: 文件不存在 - {filepath}")
        return None
    except PermissionError:
        print(f"[Security] 签名计算失败: 权限不足 - {filepath}")
        return None
    except Exception as e:
        print(f"[Security] 签名计算失败: {filepath} - {e}")
        return None


def _load_approved_signatures() -> set:
    """
    加载已批准的补丁签名列表
    从 .approved_patches 文件读取
    """
    approved = set()
    
    app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    approved_file = os.path.join(app_dir, '.approved_patches')
    
    if os.path.exists(approved_file):
        try:
            with open(approved_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # 仅提取第一个 token (签名)，忽略注释
                        approved.add(line.split()[0] if line else line)
        except Exception:
            pass
    
    return approved


# 安全配置: 允许的补丁文件名白名单
ALLOWED_PATCH_FILES = {
    'fix_crash.py',      # 崩溃修复
    'hotfix.py',         # 热修复
    'hotfix_*.py',       # 热修复 (带后缀)
    'patch_*.py',        # 通配符匹配
}

# 危险代码模式
DANGEROUS_PATTERNS = [
    'eval(', 'exec(', '__import__', 'compile(',
    'os.system', 'subprocess.', 'pty.', 'tty.',
    'socket.', 'requests.', 'urllib3.',
    'open(', 'file(', 'write(',
]


def _is_safe_patch_file(filepath: str) -> bool:
    """验证补丁文件安全性"""
    filename = os.path.basename(filepath)
    
    # 1. 检查文件名是否在白名单
    allowed = False
    for pattern in ALLOWED_PATCH_FILES:
        if fnmatch.fnmatch(filename, pattern):
            allowed = True
            break
    
    if not allowed:
        print(f"[Security] 拒绝加载未授权的补丁文件: {filename}")
        return False
    
    # 2. 检查文件内容是否有危险代码
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # AST 解析检查
        try:
            ast.parse(content)
        except SyntaxError as e:
            print(f"[Security] 补丁文件语法错误: {filename} - {e}")
            return False
        
        # 危险模式检查
        for pattern in DANGEROUS_PATTERNS:
            if pattern in content:
                print(f"[Security] 补丁文件包含危险代码: {filename} - 检测到 {pattern}")
                return False
                
    except Exception as e:
        print(f"[Security] 验证补丁文件失败: {filename} - {e}")
        return False
    
    return True


def _verify_patch_signature(filepath: str) -> bool:
    """
    验证补丁文件签名
    只有签名匹配的补丁才会被加载。
    VULN-007 修复: 未配置密钥时拒绝所有未签名补丁。
    """
    key = _get_signature_key()
    if key is None:
        print(f"[Security] 签名密钥未配置，拒绝补丁: {os.path.basename(filepath)}")
        return False
    
    signature = _compute_file_signature(filepath, key)
    approved = _load_approved_signatures()
    
    if signature in approved:
        return True
    
    print(f"[Security] 补丁 {os.path.basename(filepath)} 签名验证失败，未在批准列表中")
    return False


def _load_patches_safely(patch_dir: str):
    """安全加载补丁目录 - 需要签名验证。
    
    H-001 修复: 校验通过后通过 importlib 实际导入补丁模块。
    """
    import importlib
    import importlib.util

    if not os.path.isdir(patch_dir):
        return
    
    loaded_count = 0
    rejected_count = 0
    path_inserted = False
    
    for filename in os.listdir(patch_dir):
        if not filename.endswith('.py'):
            continue
        
        filepath = os.path.join(patch_dir, filename)
        if not os.path.isfile(filepath):
            continue
        
        mod_name = filename[:-3]  # strip .py

        # 安全验证
        if _is_safe_patch_file(filepath):
            # 签名验证
            if not _verify_patch_signature(filepath):
                print(f"[Security] 补丁 {filename} 签名验证失败，已拒绝")
                rejected_count += 1
                continue
                
            try:
                if not path_inserted:
                    sys.path.insert(0, patch_dir)
                    path_inserted = True

                # H-001 修复: 实际导入补丁模块
                spec = importlib.util.spec_from_file_location(mod_name, filepath)
                if spec is not None and spec.loader is not None:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    sys.modules[mod_name] = module
                    print(f"[Hotfix] 已安全加载补丁: {filename}")
                    loaded_count += 1
                else:
                    print(f"[Hotfix] 无法创建模块规格: {filename}")
                    rejected_count += 1
            except Exception as e:
                print(f"[Security] 加载补丁失败: {filename} - {e}")
                rejected_count += 1
    
    if loaded_count > 0:
        print(f"[Hotfix] 共加载 {loaded_count} 个已签名补丁")
    
    if rejected_count > 0:
        print(f"[Hotfix] 拒绝了 {rejected_count} 个未签名补丁")


def _create_signature_tool():
    """创建签名工具 - 用于开发者为补丁签名"""
    tool_code = '''#!/usr/bin/env python3
"""
MCA Brain System 补丁签名工具
用于为热修复补丁生成签名
"""
import os
import sys
import hashlib
import hmac

def sign_patch(patch_file: str, key: str = None):
    """为补丁文件生成签名"""
    if key is None:
        # 尝试读取密钥
        key_file = '.patch_key'
        if os.path.exists(key_file):
            with open(key_file, 'r') as f:
                key = f.read().strip()
        else:
            print("错误: 请提供密钥或创建 .patch_key 文件")
            sys.exit(1)
    else:
        key = key
    
    # 计算签名
    with open(patch_file, 'rb') as f:
        content = f.read()
    signature = hmac.new(key.encode('utf-8'), content, hashlib.sha256).hexdigest()
    
    # 添加到批准列表
    approved_file = '.approved_patches'
    with open(approved_file, 'a') as f:
        f.write(signature + '\\n')
    
    print(f"补丁已签名: {patch_file}")
    print(f"签名: {signature}")
    print(f"请将签名添加到 .approved_patches 文件")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python sign_patch.py <补丁文件> [密钥]")
        sys.exit(1)
    
    patch_file = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else None
    sign_patch(patch_file, key)
'''
    
    # 写入签名工具
    tool_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools', 'sign_patch.py')
    os.makedirs(os.path.dirname(tool_path), exist_ok=True)
    with open(tool_path, 'w', encoding='utf-8') as f:
        f.write(tool_code)
    print(f"[Hotfix] 签名工具已创建: {tool_path}")


def _validate_lib_directory(lib_dir: str) -> bool:
    """验证 lib 目录安全性"""
    if not os.path.isdir(lib_dir):
        return False
    
    # 检查是否存在危险的 .pth 文件
    for filename in os.listdir(lib_dir):
        if filename.endswith('.pth'):
            filepath = os.path.join(lib_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 检查危险代码
                    dangerous = ['import ', 'exec', 'eval', '__import__', 'os.system']
                    for pattern in dangerous:
                        if pattern in content:
                            print(f"[Security] 发现危险的 .pth 文件: {filename}")
                            return False
            except Exception:
                pass
    
    return True


# Patch loader (补丁加载器) - 安全版本 with signature verification
# 如果是以打包后的 exe 运行，尝试加载同级目录下的 'patches' 文件夹。
# 补丁必须经过签名验证才能加载
if getattr(sys, 'frozen', False):
    # Frozen runtime (打包环境)
    application_path = os.path.dirname(sys.executable)
    
    # Patches (安全加载 - 需要签名)
    patch_dir = os.path.join(application_path, "patches")
    if os.path.exists(patch_dir):
        _load_patches_safely(patch_dir)
        
    # External libs (安全验证)
    lib_dir = os.path.join(application_path, "lib")
    if os.path.exists(lib_dir):
        if _validate_lib_directory(lib_dir):
            sys.path.append(lib_dir)
            # 不使用 site.addsitedir() 以避免执行 .pth 文件
            print(f"[Launcher] 已加载外部库目录: {lib_dir}")
        else:
            print(f"[Security] lib 目录包含危险文件，已拒绝加载")
else:
    # Development environment (optional)
    # 开发环境自动创建签名工具
    pass
# End patch loader


def main():
    from config.constants import ensure_app_dirs
    ensure_app_dirs()
    
    # Start PyQt6 Silicone & Capsule UI
    try:
        import PyQt6
    except ImportError:
        print("[FATAL] PyQt6 is required but not installed.  Run: pip install PyQt6", file=sys.stderr)
        sys.exit(1)

    from PyQt6.QtWidgets import QApplication
    from mca_core.main_window_pyqt import SiliconeCapsuleApp
    print("[Launcher] Starting Silicone & Capsule UI (PyQt6)...")
    print("[Launcher] High DPI support enabled")
    app = QApplication(sys.argv)
    window = SiliconeCapsuleApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
