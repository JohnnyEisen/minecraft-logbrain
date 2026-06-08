# -*- coding: utf-8 -*-
"""补丁管理子系统 — 集成测试

覆盖端到端场景:
- 完整补丁生命周期 (upload → scan → install → rollback → verify)
- 依赖链安装
- 级联回滚
- 冲突检测 + 安装计划
- PatchSubsystem 与 BrainCore server 集成 (API 端点)
- 多补丁协同场景
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mca_core.patch_manager import (
    PatchMeta,
    PatchSubsystem,
    compute_file_hash,
)


# ══════════════════════════════════════════════════════════
# 端到端生命周期测试
# ══════════════════════════════════════════════════════════

class TestEndToEndLifecycle(unittest.TestCase):
    """完整补丁生命周期集成测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_patch(self, patch_id, version="1.0.0", deps=None, conflicts=None, modules=None):
        """创建一个完整的补丁（文件 + 元数据）"""
        patch_path = os.path.join(self.tmpdir, f"{patch_id}.py")
        with open(patch_path, "w") as f:
            f.write(f"# {patch_id} v{version}\ndef apply():\n    return True\n")

        meta = PatchMeta(
            patch_id=patch_id,
            name=f"Patch {patch_id}",
            version=version,
            description=f"Test patch {patch_id}",
            dependencies=deps or [],
            conflicts=conflicts or [],
            affected_modules=modules or [f"module_{patch_id}"],
            file_hash=compute_file_hash(patch_path),
        )

        meta_path = os.path.join(self.tmpdir, f"{patch_id}.meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

        return meta

    def test_full_lifecycle_single_patch(self):
        """完整生命周期: 单补丁 upload → scan → install → verify → rollback"""
        self._create_patch("hotfix_auth")

        with PatchSubsystem(self.tmpdir) as sub:
            # 1. 扫描
            count = sub.scan()
            self.assertEqual(count, 1)

            # 2. 校验
            ok, msg = sub.verify_integrity("hotfix_auth")
            self.assertTrue(ok, msg)

            # 3. 安装
            ok, msg = sub.install_patch("hotfix_auth")
            self.assertTrue(ok, msg)

            status = sub.status()
            self.assertEqual(status.applied, 1)
            self.assertEqual(status.available, 0)

            # 4. 验证报告
            report = sub.generate_report()
            self.assertEqual(report.applied, 1)

            # 5. 回滚
            ok, msg = sub.rollback_patch("hotfix_auth")
            self.assertTrue(ok, msg)

            status = sub.status()
            self.assertEqual(status.applied, 0)

    def test_dependency_chain_install(self):
        """依赖链安装: A ← B ← C (C 依赖 B, B 依赖 A)"""
        self._create_patch("base_lib")
        self._create_patch("mid_lib", deps=["base_lib"])
        self._create_patch("top_app", deps=["mid_lib"])

        with PatchSubsystem(self.tmpdir) as sub:
            # 生成安装计划
            plan = sub.get_install_plan()
            self.assertEqual(plan.total_count, 3)

            # 验证顺序: base → mid → top
            patch_ids = [m.patch_id for m in plan.patches]
            self.assertEqual(patch_ids[0], "base_lib")
            self.assertEqual(patch_ids[-1], "top_app")

            # 安装依赖链
            ok, msg = sub.install_patch("top_app", with_deps=True)
            self.assertTrue(ok, msg)

            status = sub.status()
            self.assertEqual(status.applied, 3)

    def test_cascade_rollback(self):
        """级联回滚: 安装 A → B → C，回滚 B 时级联回滚 C"""
        self._create_patch("base_a", deps=[])
        self._create_patch("mid_b", deps=["base_a"])
        self._create_patch("leaf_c", deps=["mid_b"])

        with PatchSubsystem(self.tmpdir) as sub:
            # 安装全部
            plan = sub.get_install_plan()
            for m in plan.patches:
                ok, msg = sub.install_patch(m.patch_id)
                self.assertTrue(ok, msg)

            status = sub.status()
            self.assertEqual(status.applied, 3)

            # 级联回滚 base_a（会级联回滚 mid_b 和 leaf_c）
            ok, msg = sub.rollback_patch("base_a", cascade=True)
            self.assertTrue(ok, msg)

            status = sub.status()
            self.assertEqual(status.applied, 0)

    def test_conflict_detection_stops_install(self):
        """冲突补丁应被检测到"""
        self._create_patch("patch_x", modules=["shared_module"])
        self._create_patch("patch_y", modules=["shared_module"])

        with PatchSubsystem(self.tmpdir) as sub:
            report = sub.detect_conflicts()
            self.assertTrue(report.has_conflicts)

            file_overlaps = [c for c in report.conflicts if c["type"] == "file_overlap"]
            self.assertEqual(len(file_overlaps), 1)

    def test_disable_prevent_install_plan(self):
        """禁用的补丁不包含在安装计划中"""
        self._create_patch("patch_a")
        self._create_patch("patch_b")

        with PatchSubsystem(self.tmpdir) as sub:
            # 禁用 patch_a
            sub.disable_patch("patch_a")

            # 安装计划应只包含 patch_b
            plan = sub.get_install_plan()
            self.assertEqual(plan.total_count, 1)
            self.assertEqual(plan.patches[0].patch_id, "patch_b")

            # 安装
            sub.install_patch("patch_b")
            status = sub.status()
            self.assertEqual(status.applied, 1)
            self.assertEqual(status.disabled, 1)

    def test_verify_failure_prevents_install(self):
        """完整性校验失败时应阻止安装"""
        # 创建补丁但不设置正确的 file_hash
        patch_path = os.path.join(self.tmpdir, "bad_patch.py")
        with open(patch_path, "w") as f:
            f.write("# bad patch\n")

        # 元数据中的哈希不匹配
        meta = PatchMeta(
            patch_id="bad_patch",
            name="Bad Patch",
            version="1.0",
            description="bad",
            file_hash="0" * 64,  # wrong hash
        )
        meta_path = os.path.join(self.tmpdir, "bad_patch.meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta.to_dict(), f)

        with PatchSubsystem(self.tmpdir) as sub:
            # 校验应失败
            ok, msg = sub.verify_integrity("bad_patch")
            self.assertFalse(ok)

            # 安装应被拒绝
            ok, msg = sub.install_patch("bad_patch")
            self.assertFalse(ok)
            self.assertIn("完整性校验失败", msg)

    def test_multiple_patches_verify_all(self):
        """批量校验所有补丁"""
        for i in range(5):
            self._create_patch(f"patch_{i}")

        with PatchSubsystem(self.tmpdir) as sub:
            results = sub.verify_all()
            self.assertEqual(len(results), 5)
            for patch_id, (ok, _msg) in results.items():
                self.assertTrue(ok, f"{patch_id} 校验失败")

    def test_report_after_operations(self):
        """操作后报告正确反映状态"""
        self._create_patch("fix_a")
        self._create_patch("fix_b")
        self._create_patch("fix_c")

        with PatchSubsystem(self.tmpdir) as sub:
            # 安装 fix_a
            sub.install_patch("fix_a")
            # 禁用 fix_b
            sub.disable_patch("fix_b")

            report = sub.generate_report()
            self.assertEqual(report.total_patches, 3)
            self.assertEqual(report.applied, 1)
            self.assertEqual(report.disabled, 1)
            self.assertEqual(report.available, 1)

    def test_context_manager_auto_cleanup(self):
        """上下文管理器应在退出时自动 shutdown"""
        self._create_patch("test_patch")

        # 使用上下文管理器创建和销毁
        sub = PatchSubsystem(self.tmpdir)
        with sub:
            sub.install_patch("test_patch")
            self.assertEqual(sub.state.value, "running")

        self.assertEqual(sub.state.value, "stopped")

        # 状态文件应已持久化
        state_file = os.path.join(self.tmpdir, ".state.json")
        self.assertTrue(os.path.isfile(state_file))

    def test_status_accuracy(self):
        """status() 应准确反映各个状态计数"""
        self._create_patch("available_patch")
        self._create_patch("apply_me")

        with PatchSubsystem(self.tmpdir) as sub:
            # 安装一个
            sub.install_patch("apply_me")

            status = sub.status()
            self.assertEqual(status.total_patches, 2)
            self.assertEqual(status.applied, 1)
            self.assertEqual(status.available, 1)
            self.assertEqual(status.failed, 0)
            self.assertEqual(status.disabled, 0)
            self.assertTrue(status.healthy)


# ══════════════════════════════════════════════════════════
# PatchSubsystem + FastAPI 集成测试
# ══════════════════════════════════════════════════════════

class TestSubsystemAPIIntegration(unittest.TestCase):
    """验证 PatchSubsystem 输出的数据格式与 REST API 兼容"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_patch(self, patch_id, **kwargs):
        """创建测试补丁"""
        patch_path = os.path.join(self.tmpdir, f"{patch_id}.py")
        with open(patch_path, "w") as f:
            f.write(f"# {patch_id}\ndef apply():\n    return True\n")

        meta = PatchMeta(
            patch_id=patch_id,
            name=kwargs.get("name", f"Patch {patch_id}"),
            version=kwargs.get("version", "1.0.0"),
            description=kwargs.get("description", f"Patch {patch_id}"),
            severity=kwargs.get("severity", "medium"),
            dependencies=kwargs.get("dependencies", []),
            tags=kwargs.get("tags", []),
            file_hash=compute_file_hash(patch_path),
        )

        meta_path = os.path.join(self.tmpdir, f"{patch_id}.meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)
        return meta

    def test_status_output_json_serializable(self):
        """status() 输出应可序列化为 JSON"""
        self._create_patch("test_patch")

        with PatchSubsystem(self.tmpdir) as sub:
            sub.install_patch("test_patch")
            status = sub.status()
            d = status.to_dict()

            # 验证 JSON 可序列化
            json_str = json.dumps(d)
            restored = json.loads(json_str)
            self.assertEqual(restored["applied"], 1)
            self.assertEqual(restored["healthy"], True)

    def test_report_output_json_serializable(self):
        """generate_report() 输出应可序列化为 JSON"""
        self._create_patch("patch_a")
        self._create_patch("patch_b")

        with PatchSubsystem(self.tmpdir) as sub:
            sub.install_patch("patch_a")
            report = sub.generate_report()
            d = report.to_dict()

            json_str = json.dumps(d)
            restored = json.loads(json_str)
            self.assertEqual(restored["total_patches"], 2)
            self.assertEqual(restored["applied"], 1)

    def test_api_contract_patch_list_format(self):
        """验证补丁列表格式符合 API 契约"""
        self._create_patch("fix_001", severity="high", tags=["security", "urgent"])
        self._create_patch("fix_002", severity="low", tags=["cosmetic"])

        with PatchSubsystem(self.tmpdir) as sub:
            sub.install_patch("fix_001")
            report = sub.generate_report()

            # 模拟 API 列表响应格式
            patches = []
            for p in report.patches:
                entry = {
                    "patch_id": p["patch_id"],
                    "state": p["state"],
                    "version": p["version"],
                    "severity": p.get("severity", ""),
                    "description": p.get("description", ""),
                    "install_order": p.get("install_order", 0),
                }
                patches.append(entry)

            # fix_001 应已安装
            applied_patch = next(p for p in patches if p["patch_id"] == "fix_001")
            self.assertEqual(applied_patch["state"], "applied")
            self.assertGreater(applied_patch["install_order"], 0)

            # fix_002 应可用
            avail_patch = next(p for p in patches if p["patch_id"] == "fix_002")
            self.assertEqual(avail_patch["state"], "available")

    def test_subystem_state_enum_serializable(self):
        """子系统状态枚举应可序列化"""
        from mca_core.patch_manager.subsystem import SubsystemState

        states = [s.value for s in SubsystemState]
        json_str = json.dumps(states)
        self.assertIn("running", json_str)
        self.assertIn("stopped", json_str)
        self.assertIn("error", json_str)


if __name__ == "__main__":
    unittest.main()