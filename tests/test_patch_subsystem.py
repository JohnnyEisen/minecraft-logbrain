# -*- coding: utf-8 -*-
"""补丁管理子系统 — 单元测试

覆盖:
- PatchSubsystem 生命周期 (initialize → startup → shutdown)
- PatchSubsystem 状态查询 (status, is_healthy)
- PatchSubsystem 委托方法 (scan, install, rollback, verify, report)
- PatchSubsystem 上下文管理器
- 数据模型 (PatchMeta, PatchRecord, PatchState)
- DependencyGraph (拓扑排序, 循环检测, 依赖链)
- 完整性校验 (SHA-256, HMAC-SHA256)
- RollbackManager (快照创建, 回滚, 级联回滚)
- PatchStore (文件存储, 状态持久化, 归档)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mca_core.patch_manager import (
    ConflictReport,
    ConflictType,
    DependencyGraph,
    InstallPlan,
    PatchManager,
    PatchMeta,
    PatchRecord,
    PatchReport,
    PatchSeverity,
    PatchState,
    PatchStore,
    PatchSubsystem,
    RollbackManager,
    SubsystemState,
    SubsystemStatus,
    compute_file_hash,
    detect_conflicts,
    get_patch_key,
    verify_file_integrity,
    verify_meta_consistency,
    verify_signature,
)


# ══════════════════════════════════════════════════════════
# PatchSubsystem 生命周期测试
# ══════════════════════════════════════════════════════════

class TestPatchSubsystemLifecycle(unittest.TestCase):
    """测试 PatchSubsystem 生命周期管理"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initial_state_is_uninitialized(self):
        sub = PatchSubsystem(self.tmpdir)
        self.assertEqual(sub.state, SubsystemState.UNINITIALIZED)
        self.assertFalse(sub.is_healthy())

    def test_initialize_transitions_to_initialized(self):
        sub = PatchSubsystem(self.tmpdir)
        ok = sub.initialize()
        self.assertTrue(ok)
        self.assertEqual(sub.state, SubsystemState.INITIALIZED)
        self.assertIsNotNone(sub.manager)

    def test_initialize_is_idempotent(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.initialize()
        ok = sub.initialize()  # second call
        self.assertTrue(ok)
        self.assertEqual(sub.state, SubsystemState.INITIALIZED)

    def test_startup_from_uninitialized_auto_initializes(self):
        sub = PatchSubsystem(self.tmpdir)
        ok = sub.startup()
        self.assertTrue(ok)
        self.assertEqual(sub.state, SubsystemState.RUNNING)
        self.assertTrue(sub.is_healthy())

    def test_startup_is_idempotent(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        ok = sub.startup()  # second call
        self.assertTrue(ok)
        self.assertEqual(sub.state, SubsystemState.RUNNING)

    def test_shutdown_from_running(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        ok = sub.shutdown()
        self.assertTrue(ok)
        self.assertEqual(sub.state, SubsystemState.STOPPED)

    def test_shutdown_is_idempotent(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        sub.shutdown()
        ok = sub.shutdown()  # second call
        self.assertTrue(ok)
        self.assertEqual(sub.state, SubsystemState.STOPPED)

    def test_shutdown_from_uninitialized_is_safe(self):
        """对未初始化的子系统调用 shutdown 应安全返回（跳过）"""
        sub = PatchSubsystem(self.tmpdir)
        ok = sub.shutdown()
        self.assertTrue(ok)
        # 从未初始化 → shutdown 跳过，状态保持 UNINITIALIZED
        self.assertEqual(sub.state, SubsystemState.UNINITIALIZED)

    def test_status_reflects_current_state(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        status = sub.status()
        self.assertEqual(status.name, "patch_management")
        self.assertEqual(status.version, "1.0.0")
        self.assertEqual(status.state, "running")
        self.assertTrue(status.healthy)

    def test_healthy_when_running(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        self.assertTrue(sub.is_healthy())

    def test_not_healthy_when_stopped(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        sub.shutdown()
        self.assertFalse(sub.is_healthy())

    def test_not_healthy_before_initialize(self):
        sub = PatchSubsystem(self.tmpdir)
        self.assertFalse(sub.is_healthy())

    def test_context_manager(self):
        with PatchSubsystem(self.tmpdir) as sub:
            self.assertEqual(sub.state, SubsystemState.RUNNING)
            self.assertTrue(sub.is_healthy())
        self.assertEqual(sub.state, SubsystemState.STOPPED)

    def test_context_manager_exception_propagates(self):
        with self.assertRaises(ValueError):
            with PatchSubsystem(self.tmpdir) as sub:
                self.assertEqual(sub.state, SubsystemState.RUNNING)
                raise ValueError("test error")
        self.assertEqual(sub.state, SubsystemState.STOPPED)

    def test_operation_before_startup_raises(self):
        sub = PatchSubsystem(self.tmpdir)
        with self.assertRaises(RuntimeError):
            sub.scan()

    def test_operation_after_shutdown_raises(self):
        sub = PatchSubsystem(self.tmpdir)
        sub.startup()
        sub.shutdown()
        with self.assertRaises(RuntimeError):
            sub.scan()

    def test_repr(self):
        sub = PatchSubsystem(self.tmpdir)
        r = repr(sub)
        self.assertIn("PatchSubsystem", r)
        self.assertIn("uninitialized", r)


# ══════════════════════════════════════════════════════════
# PatchSubsystem 委托方法测试
# ══════════════════════════════════════════════════════════

class TestPatchSubsystemOperations(unittest.TestCase):
    """测试 PatchSubsystem 委托给 PatchManager 的操作"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._create_test_patch()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_test_patch(self):
        """创建一个测试补丁文件及元数据"""
        patch_path = os.path.join(self.tmpdir, "test_fix_001.py")
        meta_path = os.path.join(self.tmpdir, "test_fix_001.meta.json")

        with open(patch_path, "w") as f:
            f.write("# test patch\ndef apply():\n    return True\n")

        meta = {
            "patch_id": "test_fix_001",
            "name": "测试补丁",
            "version": "1.0.0",
            "description": "单元测试补丁",
            "author": "Test",
            "severity": "medium",
            "dependencies": [],
            "conflicts": [],
            "replaces": [],
            "affected_modules": ["test_module"],
            "file_hash": compute_file_hash(patch_path),
            "tags": ["test"],
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f)

    def test_scan_discovers_patches(self):
        with PatchSubsystem(self.tmpdir) as sub:
            count = sub.scan()
            self.assertEqual(count, 1)
            status = sub.status()
            self.assertEqual(status.total_patches, 1)
            self.assertEqual(status.available, 1)

    def test_install_patch(self):
        with PatchSubsystem(self.tmpdir) as sub:
            ok, msg = sub.install_patch("test_fix_001")
            self.assertTrue(ok, msg)
            status = sub.status()
            self.assertEqual(status.applied, 1)
            self.assertEqual(status.available, 0)

    def test_rollback_patch(self):
        with PatchSubsystem(self.tmpdir) as sub:
            sub.install_patch("test_fix_001")
            ok, msg = sub.rollback_patch("test_fix_001")
            self.assertTrue(ok, msg)
            status = sub.status()
            self.assertEqual(status.applied, 0)

    def test_verify_integrity(self):
        with PatchSubsystem(self.tmpdir) as sub:
            ok, msg = sub.verify_integrity("test_fix_001")
            self.assertTrue(ok, msg)

    def test_generate_report(self):
        with PatchSubsystem(self.tmpdir) as sub:
            report = sub.generate_report()
            self.assertIsInstance(report, PatchReport)
            self.assertEqual(report.total_patches, 1)

    def test_get_install_plan(self):
        with PatchSubsystem(self.tmpdir) as sub:
            plan = sub.get_install_plan()
            self.assertIsInstance(plan, InstallPlan)
            self.assertEqual(plan.total_count, 1)

    def test_detect_conflicts_no_conflicts(self):
        with PatchSubsystem(self.tmpdir) as sub:
            report = sub.detect_conflicts()
            self.assertIsInstance(report, ConflictReport)
            self.assertFalse(report.has_conflicts)

    def test_disable_and_enable_patch(self):
        with PatchSubsystem(self.tmpdir) as sub:
            ok, _ = sub.disable_patch("test_fix_001")
            self.assertTrue(ok)
            status = sub.status()
            self.assertEqual(status.disabled, 1)

            ok, _ = sub.enable_patch("test_fix_001")
            self.assertTrue(ok)
            status = sub.status()
            self.assertEqual(status.disabled, 0)
            self.assertEqual(status.available, 1)

    def test_list_snapshots_after_install(self):
        with PatchSubsystem(self.tmpdir) as sub:
            sub.install_patch("test_fix_001")
            snapshots = sub.list_snapshots()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["patch_id"], "test_fix_001")

    def test_verify_all(self):
        with PatchSubsystem(self.tmpdir) as sub:
            results = sub.verify_all()
            self.assertEqual(len(results), 1)
            self.assertTrue(results["test_fix_001"][0])


# ══════════════════════════════════════════════════════════
# 数据模型测试
# ══════════════════════════════════════════════════════════

class TestModels(unittest.TestCase):
    """测试数据模型"""

    def test_patch_meta_creation(self):
        meta = PatchMeta(
            patch_id="test_001",
            name="测试补丁",
            version="1.0.0",
            description="测试描述",
            dependencies=["dep_a", "dep_b"],
            severity="high",
        )
        self.assertEqual(meta.patch_id, "test_001")
        self.assertEqual(meta.severity, "high")
        self.assertEqual(meta.dependencies, ["dep_a", "dep_b"])

    def test_patch_meta_to_from_dict_roundtrip(self):
        meta = PatchMeta(
            patch_id="test_001",
            name="测试补丁",
            version="2.0.0",
            description="描述",
            tags=["security", "urgent"],
        )
        d = meta.to_dict()
        restored = PatchMeta.from_dict(d)
        self.assertEqual(restored.patch_id, meta.patch_id)
        self.assertEqual(restored.version, meta.version)
        self.assertEqual(restored.tags, ["security", "urgent"])

    def test_patch_meta_defaults(self):
        meta = PatchMeta(patch_id="test", name="test", version="1.0", description="")
        self.assertEqual(meta.author, "MCA Security Team")
        self.assertEqual(meta.severity, "medium")
        self.assertEqual(meta.dependencies, [])
        self.assertEqual(meta.conflicts, [])
        self.assertEqual(meta.tags, [])

    def test_patch_record_creation(self):
        rec = PatchRecord(
            patch_id="test_001",
            state="applied",
            installed_version="1.0.0",
            install_order=1,
        )
        self.assertEqual(rec.state, "applied")
        self.assertEqual(rec.install_order, 1)

    def test_patch_record_roundtrip(self):
        rec = PatchRecord(patch_id="p1", state="failed", error_message="test error")
        d = rec.to_dict()
        restored = PatchRecord.from_dict(d)
        self.assertEqual(restored.patch_id, "p1")
        self.assertEqual(restored.error_message, "test error")

    def test_patch_state_enum_values(self):
        self.assertEqual(PatchState.AVAILABLE.value, "available")
        self.assertEqual(PatchState.APPLIED.value, "applied")
        self.assertEqual(PatchState.FAILED.value, "failed")
        self.assertEqual(PatchState.ROLLED_BACK.value, "rolled_back")
        self.assertEqual(PatchState.DISABLED.value, "disabled")
        self.assertEqual(PatchState.SUPERSEDED.value, "superseded")

    def test_patch_severity_enum(self):
        self.assertEqual(PatchSeverity.CRITICAL.value, "critical")
        self.assertEqual(PatchSeverity.LOW.value, "low")
        self.assertEqual(PatchSeverity.OPTIONAL.value, "optional")

    def test_conflict_type_enum(self):
        self.assertEqual(ConflictType.FILE_OVERLAP.value, "file_overlap")
        self.assertEqual(ConflictType.DEPENDENCY.value, "dependency")

    def test_subsystem_status_to_dict(self):
        status = SubsystemStatus(
            state="running",
            total_patches=5,
            applied=2,
            available=3,
            healthy=True,
        )
        d = status.to_dict()
        self.assertEqual(d["state"], "running")
        self.assertEqual(d["total_patches"], 5)
        self.assertTrue(d["healthy"])

    def test_subsystem_state_enum(self):
        self.assertEqual(SubsystemState.UNINITIALIZED.value, "uninitialized")
        self.assertEqual(SubsystemState.RUNNING.value, "running")
        self.assertEqual(SubsystemState.STOPPED.value, "stopped")


# ══════════════════════════════════════════════════════════
# DependencyGraph 测试
# ══════════════════════════════════════════════════════════

class TestDependencyGraph(unittest.TestCase):
    """测试依赖图算法"""

    def test_topological_sort_simple_chain(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=[]),
            PatchMeta("b", "B", "1.0", "", dependencies=["a"]),
            PatchMeta("c", "C", "1.0", "", dependencies=["b"]),
        ]
        dg.build(metas)
        order = dg.topological_sort()
        self.assertEqual(order, ["a", "b", "c"])

    def test_topological_sort_with_multiple_deps(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("base", "Base", "1.0", "", dependencies=[]),
            PatchMeta("lib_a", "LibA", "1.0", "", dependencies=["base"]),
            PatchMeta("lib_b", "LibB", "1.0", "", dependencies=["base"]),
            PatchMeta("app", "App", "1.0", "", dependencies=["lib_a", "lib_b"]),
        ]
        dg.build(metas)
        order = dg.topological_sort()

        # base must come first, app must come last
        self.assertEqual(order[0], "base")
        self.assertEqual(order[-1], "app")
        self.assertIn("lib_a", order[1:3])
        self.assertIn("lib_b", order[1:3])

    def test_detect_no_cycles(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=["b"]),
            PatchMeta("b", "B", "1.0", "", dependencies=[]),
        ]
        dg.build(metas)
        cycles = dg.detect_cycles()
        self.assertEqual(len(cycles), 0)

    def test_detect_cycles(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=["b"]),
            PatchMeta("b", "B", "1.0", "", dependencies=["a"]),
        ]
        dg.build(metas)
        cycles = dg.detect_cycles()
        self.assertGreater(len(cycles), 0)

    def test_topological_sort_raises_on_cycle(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=["b"]),
            PatchMeta("b", "B", "1.0", "", dependencies=["a"]),
        ]
        dg.build(metas)
        with self.assertRaises(ValueError):
            dg.topological_sort()

    def test_get_install_chain(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=[]),
            PatchMeta("b", "B", "1.0", "", dependencies=["a"]),
            PatchMeta("c", "C", "1.0", "", dependencies=["b"]),
        ]
        dg.build(metas)
        chain = dg.get_install_chain("c")
        self.assertEqual(chain, ["a", "b", "c"])

    def test_check_dependencies_satisfied(self):
        dg = DependencyGraph()
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=[]),
            PatchMeta("b", "B", "1.0", "", dependencies=["a"]),
        ]
        dg.build(metas)

        # dependency not satisfied
        ok, missing = dg.check_dependencies_satisfied("b", set())
        self.assertFalse(ok)
        self.assertIn("a", missing)

        # dependency satisfied
        ok, missing = dg.check_dependencies_satisfied("b", {"a"})
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_no_dependencies(self):
        dg = DependencyGraph()
        metas = [PatchMeta("a", "A", "1.0", "")]
        dg.build(metas)
        ok, missing = dg.check_dependencies_satisfied("a", set())
        self.assertTrue(ok)


# ══════════════════════════════════════════════════════════
# 冲突检测测试
# ══════════════════════════════════════════════════════════

class TestConflictDetection(unittest.TestCase):
    """测试冲突检测"""

    def test_file_overlap_detected(self):
        metas = [
            PatchMeta("a", "A", "1.0", "", affected_modules=["mod_x"]),
            PatchMeta("b", "B", "1.0", "", affected_modules=["mod_x"]),
        ]
        report = detect_conflicts(metas)
        self.assertTrue(report.has_conflicts)
        self.assertTrue(any(c["type"] == "file_overlap" for c in report.conflicts))

    def test_logic_conflict_detected(self):
        metas = [
            PatchMeta("a", "A", "1.0", "", conflicts=["b"]),
            PatchMeta("b", "B", "1.0", ""),
        ]
        report = detect_conflicts(metas)
        self.assertTrue(report.has_conflicts)
        self.assertTrue(any(c["type"] == "logic_conflict" for c in report.conflicts))

    def test_dependency_missing_detected(self):
        metas = [
            PatchMeta("a", "A", "1.0", "", dependencies=["nonexistent"]),
        ]
        report = detect_conflicts(metas)
        self.assertTrue(report.has_conflicts)
        self.assertTrue(any(c["type"] == "dependency" for c in report.conflicts))

    def test_no_conflicts(self):
        metas = [
            PatchMeta("a", "A", "1.0", "", affected_modules=["mod_a"]),
            PatchMeta("b", "B", "1.0", "", affected_modules=["mod_b"]),
        ]
        report = detect_conflicts(metas)
        self.assertFalse(report.has_conflicts)

    def test_conflict_report_to_dict(self):
        report = ConflictReport(has_conflicts=True, conflicts=[], resolution="resolve")
        d = report.to_dict()
        self.assertTrue(d["has_conflicts"])
        self.assertEqual(d["resolution"], "resolve")


# ══════════════════════════════════════════════════════════
# 完整性校验测试
# ══════════════════════════════════════════════════════════

class TestIntegrity(unittest.TestCase):
    """测试完整性校验"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_compute_file_hash(self):
        path = self._write_file("test.py", "hello world")
        h = compute_file_hash(path)
        self.assertEqual(len(h), 64)  # SHA-256 hex
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_verify_file_integrity_pass(self):
        path = self._write_file("test.py", "abc")
        h = compute_file_hash(path)
        self.assertTrue(verify_file_integrity(path, h))

    def test_verify_file_integrity_fail(self):
        path = self._write_file("test.py", "abc")
        self.assertFalse(verify_file_integrity(path, "0" * 64))

    def test_verify_file_integrity_nonexistent(self):
        self.assertFalse(verify_file_integrity("/nonexistent/file.py", "0" * 64))

    def test_verify_meta_consistency_valid(self):
        patch_path = self._write_file("test.py", "print('hello')")
        patch_hash = compute_file_hash(patch_path)

        meta = {
            "patch_id": "test",
            "name": "Test",
            "version": "1.0",
            "description": "test",
            "file_hash": patch_hash,
        }
        meta_path = self._write_file("test.meta.json", json.dumps(meta))

        ok, err = verify_meta_consistency(patch_path, meta_path)
        self.assertTrue(ok, err)

    def test_verify_meta_consistency_hash_mismatch(self):
        patch_path = self._write_file("test.py", "print('hello')")
        meta = {
            "patch_id": "test",
            "name": "Test",
            "version": "1.0",
            "description": "test",
            "file_hash": "0" * 64,
        }
        meta_path = self._write_file("test.meta.json", json.dumps(meta))

        ok, err = verify_meta_consistency(patch_path, meta_path)
        self.assertFalse(ok)

    def test_verify_meta_consistency_missing_fields(self):
        patch_path = self._write_file("test.py", "print('hello')")
        meta = {"patch_id": "test"}  # missing name, version, description
        meta_path = self._write_file("test.meta.json", json.dumps(meta))

        ok, err = verify_meta_consistency(patch_path, meta_path)
        self.assertFalse(ok)

    def test_get_patch_key_from_env(self):
        # 测试密钥获取（可能返回 None 如果未设置）
        key = get_patch_key()
        # 环境可能未设置，接受 None 或 bytes
        self.assertTrue(key is None or isinstance(key, bytes))

    def test_verify_signature_nonexistent_file(self):
        self.assertFalse(verify_signature("/nonexistent", b"key", "sig"))


# ══════════════════════════════════════════════════════════
# PatchStore 测试
# ══════════════════════════════════════════════════════════

class TestPatchStore(unittest.TestCase):
    """测试 PatchStore 存储层"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = PatchStore(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ensures_directories(self):
        self.assertTrue(os.path.isdir(self.store.patch_dir))
        self.assertTrue(os.path.isdir(self.store.rollback_dir))
        self.assertTrue(os.path.isdir(self.store.archive_dir))

    def test_list_patch_files_empty(self):
        files = self.store.list_patch_files()
        self.assertEqual(files, [])

    def test_write_and_read_meta(self):
        meta = PatchMeta(
            patch_id="test_001", name="Test", version="1.0",
            description="test desc", tags=["test"],
        )
        self.store.write_meta(meta)

        loaded = self.store.read_meta("test_001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.patch_id, "test_001")
        self.assertEqual(loaded.version, "1.0")
        self.assertEqual(loaded.tags, ["test"])

    def test_load_all_meta(self):
        for i in range(3):
            meta = PatchMeta(f"patch_{i}", f"Patch {i}", "1.0", f"desc {i}")
            self.store.write_meta(meta)

        all_meta = self.store.load_all_meta()
        self.assertEqual(len(all_meta), 3)

    def test_persist_and_load_state(self):
        state = {
            "p1": PatchRecord(patch_id="p1", state="applied", install_order=1),
            "p2": PatchRecord(patch_id="p2", state="available"),
        }
        self.store.save_state(state)

        loaded = self.store.load_state()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded["p1"].state, "applied")
        self.assertEqual(loaded["p1"].install_order, 1)

    def test_save_and_load_rollback_point(self):
        from mca_core.patch_manager.models import RollbackPoint

        rp = RollbackPoint(
            point_id="rb_test_001",
            created_at="2026-01-01T00:00:00",
            patch_id="patch_a",
            patch_version="1.0",
            state_snapshot={"a": "b"},
            checksum="abc123",
        )
        self.store.save_rollback_point(rp)

        loaded = self.store.load_rollback_point("rb_test_001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.patch_id, "patch_a")
        self.assertEqual(loaded.checksum, "abc123")

    def test_upload_and_archive_patch(self):
        src = os.path.join(self.tmpdir, "_src.py")
        with open(src, "w") as f:
            f.write("# test")

        dest = self.store.upload_patch(src, "patch_x")
        self.assertTrue(os.path.isfile(dest))

        # archive
        self.store.archive_patch("patch_x")
        self.assertFalse(os.path.isfile(dest))

    def test_delete_meta(self):
        meta = PatchMeta("del_me", "Del", "1.0", "")
        self.store.write_meta(meta)
        self.assertIsNotNone(self.store.read_meta("del_me"))

        self.store.delete_meta("del_me")
        self.assertIsNone(self.store.read_meta("del_me"))


if __name__ == "__main__":
    unittest.main()