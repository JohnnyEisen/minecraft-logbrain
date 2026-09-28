"""测试补丁沙箱执行和验证器的安全性。"""
import pytest

from mca_core.patch_manager.patch_sandbox import execute_patch_sandboxed, PermissionLevel
from mca_core.patch_manager.patch_validator import (
    PatchValidator, RiskLevel, validate_patch_code,
)


class TestPatchValidator:
    """补丁代码验证器安全测试"""

    def test_valid_patch(self):
        r = validate_patch_code("def apply():\n    return 1 + 2\n", "valid")
        assert r.is_valid
        assert r.risk_level == "safe"

    def test_no_apply_rejected(self):
        r = validate_patch_code("def not_apply():\n    pass\n", "no_apply")
        assert not r.is_valid
        assert any("apply()" in e for e in r.errors)

    def test_exec_rejected(self):
        r = validate_patch_code("def apply():\n    exec('x=1')\n", "exec_patch")
        assert not r.is_valid
        assert any("exec" in e.lower() for e in r.errors)

    def test_subprocess_is_high_risk(self):
        r = validate_patch_code(
            "import subprocess\ndef apply():\n    subprocess.run(['ls'])\n", "high")
        assert r.risk_level == "high"

    def test_empty_code_rejected(self):
        r = validate_patch_code("", "empty")
        assert not r.is_valid

    def test_safe_imports(self):
        r = validate_patch_code(
            "import math\nfrom collections import defaultdict\ndef apply():\n    return math.sqrt(16)\n", "safe")
        assert r.is_valid
        assert r.risk_level == "safe"

    def test_file_write_is_medium_risk(self):
        r = validate_patch_code(
            "def apply():\n    with open('test.txt', 'w') as f:\n        f.write('x')\n", "write")
        assert r.risk_level == "medium"

    def test_module_level_code_warning(self):
        r = validate_patch_code(
            "print('hello')\n\ndef apply():\n    pass\n", "module_code")
        assert not r.is_valid or len(r.warnings) > 0


class TestPatchSandbox:
    """补丁沙箱执行安全测试"""

    def test_safe_patch_restricted(self):
        r = execute_patch_sandboxed(
            "def apply():\n    return sum(range(100))\n", "safe", PermissionLevel.RESTRICTED)
        assert r.success, r.message

    def test_no_apply_sandbox(self):
        r = execute_patch_sandboxed(
            "def not_apply():\n    pass\n", "no_apply", PermissionLevel.RESTRICTED)
        assert not r.success

    def test_restricted_write_blocked(self):
        r = execute_patch_sandboxed(
            "def apply():\n    open('test.txt', 'w')\n", "write", PermissionLevel.RESTRICTED)
        assert not r.success, r.message

    def test_exec_blocked_in_admin(self):
        r = execute_patch_sandboxed(
            "def apply():\n    exec('x=1')\n", "exec", PermissionLevel.ADMIN)
        assert not r.success, r.message

    def test_admin_os_import_blocked(self):
        """VULN-003 修复: admin 级别也应阻止 os/subprocess 等危险模块导入。"""
        r = execute_patch_sandboxed(
            "import os\ndef apply():\n    return os.getcwd()\n", "admin", PermissionLevel.ADMIN)
        assert not r.success, f"os import should be blocked in sandbox: {r.message}"

    def test_admin_safe_math_allowed(self):
        """admin 级别允许白名单中的安全模块（如 math）。"""
        r = execute_patch_sandboxed(
            "import math\ndef apply():\n    return math.sqrt(16)\n", "admin_safe", PermissionLevel.ADMIN)
        assert r.success, r.message

    def test_syntax_error_caught(self):
        r = execute_patch_sandboxed(
            "def apply()\n    pass\n", "syntax", PermissionLevel.RESTRICTED)
        assert not r.success

    def test_eval_blocked(self):
        r = execute_patch_sandboxed(
            "def apply():\n    eval('1+2')\n", "eval", PermissionLevel.ADMIN)
        assert not r.success, r.message

# ── VULN-001 回归: 帧攀爬沙箱逃逸必须被拒 ──
def test_sandbox_blocks_traceback_frame_escape(tmp_path):
    """红队实战载荷: __traceback__.tb_frame + f_back 攀爬取真实 builtins。"""
    from mca_core.patch_manager.patch_sandbox import (
        PermissionLevel,
        execute_patch_sandboxed,
    )

    marker = tmp_path / "pwned_marker.txt"
    escape_code = (
        "try:\n"
        "    raise RuntimeError('boom')\n"
        "except Exception as _e:\n"
        "    _f = _e.__traceback__.tb_frame\n"
        "    while _f is not None:\n"
        "        _b = _f.f_globals.get('__builtins__')\n"
        "        if _b is not None:\n"
        "            _bi = _b if isinstance(_b, dict) else vars(_b)\n"
        "            if 'open' in _bi:\n"
        "                break\n"
        "        _f = _f.f_back\n"
        "    _bi['open'](r'" + str(marker) + "', 'w').write('ESCAPED')\n"
        "\n"
        "def apply():\n"
        "    return 'x'\n"
    )
    result = execute_patch_sandboxed(
        code=escape_code, patch_id="vuln001_regression",
        level=PermissionLevel.RESTRICTED,
    )
    assert not result.success, f"逃逸载荷被执行成功: {result.message}"
    assert not marker.exists(), "标记文件被写入，沙箱被逃逸"


def test_sandbox_blocks_getattr_frame_pivot(tmp_path):
    """getattr(name) 形式的帧属性枢轴也必须被运行时代理拦截。"""
    from mca_core.patch_manager.patch_sandbox import (
        PermissionLevel,
        execute_patch_sandboxed,
    )

    escape_code = (
        "def apply():\n"
        "    _parts = ['tb_', 'frame']\n"
        "    _name = _parts[0] + _parts[1]\n"
        "    try:\n"
        "        raise RuntimeError('boom')\n"
        "    except Exception as _e:\n"
        "        getattr(_e, _name)\n"
        "    return 'x'\n"
    )
    result = execute_patch_sandboxed(
        code=escape_code, patch_id="vuln001_getattr",
        level=PermissionLevel.RESTRICTED,
    )
    assert not result.success, "getattr 帧属性枢轴未被拦截"
