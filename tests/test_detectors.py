"""
核心检测器单元测试。

测试覆盖：
- OutOfMemoryDetector
- MissingDependenciesDetector
- VersionConflictsDetector
- DuplicateModsDetector
- JvmIssuesDetector
- MixinConflictsDetector
- ShaderWorldConflictsDetector
- DetectorCache (缓存状态检测、命中率计算)
- 检测器注册与发现
"""

import unittest
import sys
import os
import time
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mca_core.detectors.base import Detector
from mca_core.detectors.contracts import AnalysisContext, DetectionResult
from mca_core.detectors.out_of_memory import OutOfMemoryDetector
from mca_core.detectors.missing_dependencies import MissingDependenciesDetector
from mca_core.detectors.duplicate_mods import DuplicateModsDetector
from mca_core.detectors.jvm_issues import JvmIssuesDetector
from mca_core.detectors.mixin_conflicts import MixinConflictsDetector
from mca_core.detectors.version_conflicts import VersionConflictsDetector
from mca_core.detectors.shader_world_conflicts import ShaderWorldConflictsDetector
from mca_core.detectors.cache import (
    DetectorCache, CacheEntry, CacheStats,
    get_detector_cache, reset_detector_cache
)


class MockAnalyzer:
    """模拟分析器，用于测试。"""
    
    def __init__(self):
        self.analysis_results = []
        self.cause_counts = {}
        self.lock = None
        self.mods = {}
        self.conflict_db = {}
    
    def add_cause(self, label: str):
        self.cause_counts[label] = self.cause_counts.get(label, 0) + 1


class TestDetectorInterface(unittest.TestCase):
    """检测器接口测试。"""
    
    def test_detection_result_dataclass(self):
        """DetectionResult 应该正确初始化。"""
        result = DetectionResult(
            message="Test message",
            detector="TestDetector",
            cause_label="TestCause"
        )
        self.assertEqual(result.message, "Test message")
        self.assertEqual(result.detector, "TestDetector")
        self.assertEqual(result.cause_label, "TestCause")
        self.assertEqual(result.metadata, {})
    
    def test_analysis_context_initialization(self):
        """AnalysisContext 应该正确初始化。"""
        analyzer = MockAnalyzer()
        ctx = AnalysisContext(analyzer=analyzer, crash_log="test log")
        self.assertEqual(ctx.crash_log, "test log")
        self.assertEqual(ctx.results, [])
        self.assertEqual(ctx.cause_counts, {})


class TestOutOfMemoryDetector(unittest.TestCase):
    """内存溢出检测器测试。"""
    
    def setUp(self):
        self.detector = OutOfMemoryDetector()
        self.analyzer = MockAnalyzer()
    
    def test_detector_metadata(self):
        """检测器元数据应正确。"""
        self.assertEqual(self.detector.get_name(), "MemoryDetector")
        self.assertEqual(self.detector.get_cause_label(), "内存溢出")
    
    def test_detect_oom_error(self):
        """OutOfMemoryError 应被检测。"""
        log = """
        java.lang.OutOfMemoryError: Java heap space
        at java.util.Arrays.copyOf(Arrays.java:3332)
        """
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        self.assertTrue(len(results) > 0)
        self.assertTrue(any("内存溢出" in r.message for r in results))
        self.assertIn("内存溢出", ctx.cause_counts)
    
    def test_detect_out_of_memory_phrase(self):
        """'out of memory' 短语应被检测。"""
        log = "Error: out of memory while loading chunks"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        self.assertTrue(len(results) > 0)
        self.assertTrue(any("内存溢出" in r.message for r in results))
    
    def test_no_memory_error(self):
        """无内存问题的日志不应触发。"""
        log = "Everything is fine. No errors here."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        self.assertEqual(len(results), 0)
    
    def test_case_insensitive(self):
        """检测应不区分大小写。"""
        log = "OUTOFMEMORYERROR: Something went wrong"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        self.assertTrue(len(results) > 0)
    
    def test_empty_log(self):
        """空日志应安全处理。"""
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)


class TestMissingDependenciesDetector(unittest.TestCase):
    """缺失依赖检测器测试。"""
    
    def setUp(self):
        self.detector = MissingDependenciesDetector()
        self.analyzer = MockAnalyzer()
    
    def test_detector_metadata(self):
        """检测器元数据应正确。"""
        self.assertEqual(self.detector.get_name(), "DependencyDetector")
        self.assertEqual(self.detector.get_cause_label(), "缺失依赖")
    
    def test_detect_missing_mod_block(self):
        """ModSorter 格式的缺失依赖应被检测。"""
        log = """
        Missing or unsupported mandatory dependencies:
        Mod ID: 'geckolib', Requested by: ' draconicevolution ', Expected range: '[1.0.0,)', Actual version: '[MISSING]'
        """
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        # 注意：detect 方法可能返回 None，结果存储在 ctx.results 中
        if results is not None:
            self.assertTrue(len(results) > 0)
        else:
            # 结果存储在 context 中
            self.assertTrue(len(ctx.results) > 0)
        
        # 应该包含详细的依赖信息
        combined = " ".join(r.message for r in ctx.results)
        self.assertIn("geckolib", combined.lower())
    
    def test_detect_simple_missing(self):
        """简单的 'missing' 关键词应被检测。"""
        log = "Error: missing geckolib dependency"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        self.detector.detect(log, ctx)
        
        self.assertTrue(len(ctx.results) > 0)

    def test_detect_requires_keyword(self):
        """Mod ID 格式的缺失依赖应被检测。"""
        log = "Mod ID: 'geckolib3', Requested by: 'dragonmounts'"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        self.detector.detect(log, ctx)
        
        # 结果存储在 context 中
        self.assertTrue(len(ctx.results) > 0)
    
    def test_no_missing_dependency(self):
        """无缺失依赖的日志不应触发。"""
        log = "All mods loaded successfully"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        self.assertEqual(len(results), 0)
    
    def test_filters_invalid_mod_names(self):
        """无效的模组名应被过滤。"""
        log = "missing or: something went wrong"  # "or" 是无效的mod名
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        
        # "or" 应该被过滤掉，不产生结果
        self.assertEqual(len(results), 0)
    
    def test_empty_log(self):
        """空日志应安全处理。"""
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)


class TestAnalysisContext(unittest.TestCase):
    """AnalysisContext 功能测试。"""
    
    def test_add_result(self):
        """add_result 应正确添加结果。"""
        analyzer = MockAnalyzer()
        ctx = AnalysisContext(analyzer=analyzer, crash_log="")
        
        ctx.add_result("Test message", "TestDetector", "TestCause")
        
        self.assertEqual(len(ctx.results), 1)
        self.assertEqual(ctx.results[0].message, "Test message")
        self.assertIn("TestCause", ctx.cause_counts)
    
    def test_add_result_updates_analyzer(self):
        """add_result 应更新 analyzer 的 analysis_results。"""
        analyzer = MockAnalyzer()
        ctx = AnalysisContext(analyzer=analyzer, crash_log="")
        
        ctx.add_result("Test message", "TestDetector")
        
        self.assertIn("Test message", analyzer.analysis_results)
    
    def test_add_result_block(self):
        """add_result_block 应添加完整的结果块。"""
        analyzer = MockAnalyzer()
        ctx = AnalysisContext(analyzer=analyzer, crash_log="")
        
        ctx.add_result_block(
            header="Header message",
            items=["  - item 1", "  - item 2"],
            detector="TestDetector",
            cause_label="TestCause"
        )
        
        self.assertEqual(len(ctx.results), 3)  # header + 2 items
        self.assertEqual(ctx.results[0].message, "Header message")
    
    def test_context_without_analyzer(self):
        """无 analyzer 的 context 应能工作。"""
        ctx = AnalysisContext(analyzer=None, crash_log="test")
        
        ctx.add_result("Test message", "TestDetector")
        
        self.assertEqual(len(ctx.results), 1)


class TestDetectorIntegration(unittest.TestCase):
    """检测器集成测试。"""
    
    def test_multiple_detectors_same_context(self):
        """多个检测器可以共享同一个 context。"""
        oom_detector = OutOfMemoryDetector()
        dep_detector = MissingDependenciesDetector()
        
        analyzer = MockAnalyzer()
        log = """
        java.lang.OutOfMemoryError: Java heap space
        Also missing mod 'geckolib'
        """
        ctx = AnalysisContext(analyzer=analyzer, crash_log=log)
        
        oom_detector.detect(log, ctx)
        dep_detector.detect(log, ctx)
        
        # 应该有来自两个检测器的结果
        self.assertTrue(len(ctx.results) >= 2)
        self.assertIn("内存溢出", ctx.cause_counts)
        self.assertIn("缺失依赖", ctx.cause_counts)
    
    def test_real_world_crash_log(self):
        """真实崩溃日志测试。"""
        log = """
        ---- Minecraft Crash Report ----
        // This is a test crash
        
        Time: 2024-01-15 10:30:00
        Description: Unexpected error
        
        java.lang.OutOfMemoryError: Java heap space
        at java.util.Arrays.copyOf(Arrays.java:3332)
        at java.util.Arrays.copyOf(Arrays.java:3310)
        
        A detailed walkthrough of the error:
        Missing or unsupported mandatory dependencies:
        Mod ID: 'geckolib3', Requested by: 'dragonmounts', Expected range: '[3.0.0,)'
        """
        
        analyzer = MockAnalyzer()
        ctx = AnalysisContext(analyzer=analyzer, crash_log=log)
        
        OutOfMemoryDetector().detect(log, ctx)
        MissingDependenciesDetector().detect(log, ctx)
        
        # 应该检测到两个问题
        self.assertGreaterEqual(len(ctx.results), 2)


# ============================================================
# DetectorCache 测试 (任务 2.1 - cache.py)
# ============================================================

class TestCacheEntry(unittest.TestCase):
    """CacheEntry 数据类测试。"""

    def test_creation(self):
        entry = CacheEntry(
            key="abc123",
            results=[],
            created_at=time.time(),
            expires_at=time.time() + 300,
        )
        self.assertEqual(entry.key, "abc123")
        self.assertEqual(entry.results, [])
        self.assertEqual(entry.hit_count, 0)
        self.assertEqual(entry.size_bytes, 0)

    def test_not_expired(self):
        entry = CacheEntry(
            key="test",
            results=[],
            created_at=time.time(),
            expires_at=time.time() + 3600,
        )
        self.assertFalse(entry.is_expired())

    def test_expired(self):
        entry = CacheEntry(
            key="test",
            results=[],
            created_at=time.time() - 7200,
            expires_at=time.time() - 3600,
        )
        self.assertTrue(entry.is_expired())

    def test_hit_count_tracking(self):
        entry = CacheEntry(
            key="test",
            results=[],
            created_at=time.time(),
            expires_at=time.time() + 3600,
            hit_count=5,
        )
        self.assertEqual(entry.hit_count, 5)


class TestCacheStats(unittest.TestCase):
    """CacheStats 数据类测试。"""

    def test_hit_rate_zero_when_no_requests(self):
        stats = CacheStats()
        self.assertEqual(stats.hit_rate, 0.0)

    def test_hit_rate_calculation(self):
        stats = CacheStats(hits=75, misses=25)
        self.assertEqual(stats.hit_rate, 0.75)

    def test_hit_rate_perfect(self):
        stats = CacheStats(hits=100, misses=0)
        self.assertEqual(stats.hit_rate, 1.0)

    def test_hit_rate_all_misses(self):
        stats = CacheStats(hits=0, misses=100)
        self.assertEqual(stats.hit_rate, 0.0)

    def test_to_dict(self):
        stats = CacheStats(hits=50, misses=50, evictions=5, size=10, max_size=100)
        d = stats.to_dict()
        self.assertEqual(d["hits"], 50)
        self.assertEqual(d["misses"], 50)
        self.assertEqual(d["evictions"], 5)
        self.assertEqual(d["size"], 10)
        self.assertEqual(d["max_size"], 100)
        self.assertIn("hit_rate", d)
        self.assertIn("memory_mb", d)


class TestDetectorCache(unittest.TestCase):
    """DetectorCache 核心功能测试。"""

    def setUp(self):
        reset_detector_cache()
        self.cache = DetectorCache(max_size=10, max_memory_mb=50, ttl_seconds=60)

    def test_compute_key(self):
        key1 = DetectorCache.compute_key("test log")
        key2 = DetectorCache.compute_key("test log")
        key3 = DetectorCache.compute_key("different log")
        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)
        self.assertEqual(len(key1), 32)

    def test_get_miss(self):
        result = self.cache.get("nonexistent")
        self.assertIsNone(result)
        stats = self.cache.get_stats()
        self.assertEqual(stats.misses, 1)

    def test_set_and_get(self):
        results = [DetectionResult(message="test", detector="TestDetector")]
        self.cache.set("key1", results)
        cached = self.cache.get("key1")
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].message, "test")
        stats = self.cache.get_stats()
        self.assertEqual(stats.hits, 1)

    def test_has_existing(self):
        self.cache.set("key1", [])
        self.assertTrue(self.cache.has("key1"))

    def test_has_nonexistent(self):
        self.assertFalse(self.cache.has("missing_key"))

    def test_delete(self):
        self.cache.set("key1", [])
        self.assertTrue(self.cache.delete("key1"))
        self.assertFalse(self.cache.has("key1"))

    def test_delete_nonexistent(self):
        self.assertFalse(self.cache.delete("nonexistent"))

    def test_clear(self):
        self.cache.set("k1", [])
        self.cache.set("k2", [])
        self.cache.clear()
        stats = self.cache.get_stats()
        self.assertEqual(stats.size, 0)
        self.assertEqual(stats.memory_bytes, 0)

    def test_ttl_expiration(self):
        results = [DetectionResult(message="expired", detector="Test")]
        self.cache.set("key1", results, ttl_seconds=0.01)
        time.sleep(0.02)
        cached = self.cache.get("key1")
        self.assertIsNone(cached)
        stats = self.cache.get_stats()
        self.assertEqual(stats.misses, 1)

    def test_has_with_expired_entry(self):
        self.cache.set("key1", [], ttl_seconds=0.01)
        time.sleep(0.02)
        self.assertFalse(self.cache.has("key1"))

    def test_lru_eviction_by_count(self):
        cache = DetectorCache(max_size=3, ttl_seconds=3600)
        for i in range(4):
            cache.set(f"key{i}", [DetectionResult(message=str(i), detector="Test")])
        stats = cache.get_stats()
        self.assertEqual(stats.size, 3)
        self.assertEqual(stats.evictions, 1)
        self.assertFalse(cache.has("key0"))

    def test_lru_order_after_get(self):
        cache = DetectorCache(max_size=3, ttl_seconds=3600)
        cache.set("a", [DetectionResult(message="a", detector="Test")])
        cache.set("b", [DetectionResult(message="b", detector="Test")])
        cache.set("c", [DetectionResult(message="c", detector="Test")])
        cache.get("a")
        cache.set("d", [DetectionResult(message="d", detector="Test")])
        self.assertTrue(cache.has("a"))
        self.assertTrue(cache.has("c"))
        self.assertTrue(cache.has("d"))
        self.assertFalse(cache.has("b"))

    def test_cleanup_expired(self):
        cache = DetectorCache(max_size=10, ttl_seconds=3600)
        cache.set("keep", [])
        cache.set("expire1", [], ttl_seconds=0.01)
        cache.set("expire2", [], ttl_seconds=0.01)
        time.sleep(0.02)
        removed = cache.cleanup()
        self.assertEqual(removed, 2)
        self.assertTrue(cache.has("keep"))
        self.assertFalse(cache.has("expire1"))

    def test_cleanup_no_expired(self):
        self.cache.set("k1", [])
        removed = self.cache.cleanup()
        self.assertEqual(removed, 0)

    def test_hit_count_increments(self):
        results = [DetectionResult(message="hits", detector="Test")]
        self.cache.set("key1", results)
        self.cache.get("key1")
        self.cache.get("key1")
        self.cache.get("key1")
        self.cache.get("missing")
        stats = self.cache.get_stats()
        self.assertEqual(stats.hits, 3)
        self.assertEqual(stats.misses, 1)

    def test_overwrite_existing(self):
        r1 = [DetectionResult(message="v1", detector="Test")]
        r2 = [DetectionResult(message="v2", detector="Test")]
        self.cache.set("key1", r1)
        self.cache.set("key1", r2)
        cached = self.cache.get("key1")
        self.assertEqual(cached[0].message, "v2")
        stats = self.cache.get_stats()
        self.assertEqual(stats.evictions, 0)

    def test_memory_based_eviction(self):
        cache = DetectorCache(max_size=1000, max_memory_mb=0, ttl_seconds=3600)
        r = [DetectionResult(message="x" * 1000, detector="Test")]
        cache.set("k1", r)
        cache.set("k2", r)
        self.assertFalse(cache.has("k1"))

    def test_stats_thread_safety(self):
        import threading
        cache = DetectorCache(max_size=100, ttl_seconds=3600)
        errors = []

        def worker():
            try:
                for i in range(50):
                    key = f"key-{threading.get_ident()}-{i}"
                    cache.set(key, [DetectionResult(message=str(i), detector="Test")])
                    cache.get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(errors), 0)

    def test_estimate_size(self):
        r = [
            DetectionResult(message="test", detector="TestDetector", cause_label="TestCause",
                          metadata={"key": "value"})
        ]
        size = self.cache._estimate_size(r)
        self.assertGreater(size, 0)


class TestGlobalDetectorCache(unittest.TestCase):
    """全局 DetectorCache 单例测试。"""

    def tearDown(self):
        reset_detector_cache()

    def test_singleton(self):
        c1 = get_detector_cache()
        c2 = get_detector_cache()
        self.assertIs(c1, c2)

    def test_reset_creates_new(self):
        c1 = get_detector_cache()
        c1.set("key", [DetectionResult(message="test", detector="Test")])
        reset_detector_cache()
        c2 = get_detector_cache()
        self.assertFalse(c2.has("key"))


# ============================================================
# DuplicateModsDetector 测试 (任务 2.1 - duplicate_mods.py)
# ============================================================

class TestDuplicateModsDetector(unittest.TestCase):
    """重复 Mod 检测器测试。"""

    def setUp(self):
        self.detector = DuplicateModsDetector()
        self.analyzer = MockAnalyzer()

    def test_metadata(self):
        self.assertEqual(self.detector.get_name(), "DuplicateModsDetector")

    def test_no_duplicates(self):
        log = "All mods loaded successfully."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_empty_log(self):
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)

    def test_detect_duplicate_jar(self):
        jar_name = "somemod-1.0.0"
        log = (f"{jar_name}.jar\n" * 20)
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("duplicate", combined.lower())

    def test_ignore_system_jars(self):
        jar_name = "forge-1.0.0"
        log = (f"{jar_name}.jar\n" * 20)
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_ignore_below_threshold(self):
        jar_name = "testmod-1.0.0"
        log = (f"{jar_name}.jar\n" * 5)
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_ignore_loader_keywords(self):
        jar_name = "somelauncher-2.0.0"
        log = (f"{jar_name}.jar\n" * 20)
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_detect_mod_level_duplicates(self):
        self.analyzer.mods = {"mytestmod": "1.0"}
        log = ("mytestmod-1.0.0.jar\n" * 20)
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_empty_modid_skipped(self):
        self.analyzer.mods = {"": "1.0", "testmod": "1.0"}
        log = ("testmod-1.0.0.jar\n" * 20)
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_numeric_only_modid_skipped(self):
        self.analyzer.mods = {"12345": "1.0", "testmod": "1.0"}
        log = "No duplicates here."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_mod_pattern_caching(self):
        modid = "cachedmod"
        p1 = DuplicateModsDetector._get_mod_pattern(modid)
        p2 = DuplicateModsDetector._get_mod_pattern(modid)
        self.assertIs(p1, p2)
        self.assertIn(modid, DuplicateModsDetector._mod_patterns)

    def test_mod_pattern_cache_limit(self):
        for i in range(DuplicateModsDetector._MOD_PATTERNS_MAX + 5):
            DuplicateModsDetector._get_mod_pattern(f"mod{i}")
        self.assertLessEqual(len(DuplicateModsDetector._mod_patterns),
                            DuplicateModsDetector._MOD_PATTERNS_MAX)

    def test_multiple_different_jars(self):
        log = "\n".join([
            *(["moda-1.0.0.jar"] * 16),
            *(["modb-2.0.0.jar"] * 16),
            *(["modc-3.0.0.jar"] * 5),
        ])
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)


# ============================================================
# JvmIssuesDetector 测试 (任务 2.1 - jvm_issues.py)
# ============================================================

class TestJvmIssuesDetector(unittest.TestCase):
    """JVM 问题检测器测试。"""

    def setUp(self):
        self.detector = JvmIssuesDetector()
        self.analyzer = MockAnalyzer()

    def test_metadata(self):
        self.assertEqual(self.detector.get_name(), "JvmIssuesDetector")
        self.assertIsNone(self.detector.get_cause_label())

    def test_empty_log(self):
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)

    def test_no_issues(self):
        log = "All systems nominal."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_no_class_def_found(self):
        log = "Error: java.lang.NoClassDefFoundError: com/example/MyClass"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("NoClassDefFoundError", combined)

    def test_class_not_found(self):
        log = "Caused by: java.lang.ClassNotFoundException: net.minecraft.server.MinecraftServer"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("ClassNotFoundException", combined)

    def test_jvm_version_incompatible(self):
        log = "UnsupportedClassVersionError: unsupported class file major version 61"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("版本不兼容", combined)

    def test_jvm_version_incompatible_with_java_version(self):
        log = (
            "UnsupportedClassVersionError: version 61\n"
            "Java Version: 8"
        )
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("版本不兼容", combined)

    def test_incompatible_jvm_args(self):
        log = "JVM Flags: -XX:+UseConcMarkSweepGC -Xmx4G"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("CMS GC", combined)

    def test_incompatible_max_permsize(self):
        log = "JVM Flags: -XX:MaxPermSize=256m"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("MaxMetaspaceSize", combined)

    def test_jvm_creation_failed(self):
        log = "Error: Could not create the Java Virtual Machine."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("JVM 创建失败", combined)

    def test_fatal_exception(self):
        log = "A fatal exception has occurred. Program will exit."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("JVM 崩溃", combined)

    def test_extract_java_version_from_config(self):
        log = "java.version = 17.0.5"
        version = self.detector._extract_java_version(log)
        self.assertEqual(version, 17)

    def test_extract_java_version_openjdk(self):
        log = 'OpenJDK Runtime Environment (build 21+35) version "21"'
        version = self.detector._extract_java_version(log)
        self.assertEqual(version, 21)

    def test_extract_jvm_args(self):
        log = "JVM Flags: -Xmx4G -Xms2G -XX:+UseG1GC"
        args = self.detector._extract_jvm_args(log)
        self.assertEqual(len(args), 3)
        self.assertIn("-Xmx4G", args)

    def test_extract_jvm_args_none(self):
        args = self.detector._extract_jvm_args("no flags here")
        self.assertEqual(args, [])

    def test_extract_java_version_not_found(self):
        version = self.detector._extract_java_version("no java version here")
        self.assertIsNone(version)

    def test_incompatible_jvm_arg_key_match(self):
        log = "JVM Flags: -XX:PermSize=256m"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("MetaspaceSize", combined)


# ============================================================
# MixinConflictsDetector 测试 (任务 2.1 - mixin_conflicts.py)
# ============================================================

class TestMixinConflictsDetector(unittest.TestCase):
    """Mixin 冲突检测器测试。"""

    def setUp(self):
        self.detector = MixinConflictsDetector()
        self.analyzer = MockAnalyzer()

    def test_metadata(self):
        self.assertEqual(self.detector.get_name(), "MixinConflictsDetector")

    def test_empty_log(self):
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)

    def test_no_mixin_issues(self):
        log = "Everything loaded fine."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_invalid_injection_exception(self):
        log = "InvalidInjectionException: Invalid descriptor on com/example/MyClass:methodName"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("InvalidInjectionException", combined)

    def test_invalid_descriptor_with_details(self):
        log = (
            "InvalidInjectionException\n"
            "Invalid descriptor on com/example/MyClass:myMethod(Ljava/lang/String;)V"
        )
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("MyClass", combined)

    def test_mixin_apply_failed(self):
        log = "Error: Mixin apply failed for mixins.example.json"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("Mixin error", combined)

    def test_mixin_configuration_error(self):
        log = "Invalid Mixin configuration detected"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_mixin_transformation_error(self):
        log = "Mixin transformation error occurred"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_critical_injection_failure(self):
        log = "Critical injection failure in mixin"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_extracts_mixin_names(self):
        log = (
            "Mixin apply failed\n"
            "mixins.example.json\n"
            "mixin.conflict.test.json\n"
        )
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_multiple_warnings_trigger(self):
        log = (
            "Mixin some_mod conflict detected\n"
            "Mixin another_mod error found\n"
        )
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("compatibility", combined.lower())

    def test_single_warning_no_trigger(self):
        log = "Mixin some_mod conflict detected"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_incompatible_mixin_config(self):
        log = "Found incompatible mixin configuration"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_mixin_could_not_be_applied(self):
        log = "Mixin some_mixin could not be applied"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_get_error_patterns_cached(self):
        p1 = MixinConflictsDetector._get_error_patterns()
        p2 = MixinConflictsDetector._get_error_patterns()
        self.assertIs(p1, p2)

    def test_get_warning_patterns_cached(self):
        p1 = MixinConflictsDetector._get_warning_patterns()
        p2 = MixinConflictsDetector._get_warning_patterns()
        self.assertIs(p1, p2)

    def test_invalid_injection_without_descriptor(self):
        log = "InvalidInjectionException\nSome other details\nBut no descriptor line"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("InvalidInjectionException", combined)


# ============================================================
# VersionConflictsDetector 测试 (任务 2.1 - version_conflicts.py)
# ============================================================

class TestVersionConflictsDetector(unittest.TestCase):
    """版本冲突检测器测试。"""

    def setUp(self):
        self.detector = VersionConflictsDetector()
        self.analyzer = MockAnalyzer()

    def test_metadata(self):
        self.assertEqual(self.detector.get_name(), "VersionConflictDetector")
        self.assertEqual(self.detector.get_priority(), 10)

    def test_empty_log(self):
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)

    def test_no_conflicts(self):
        log = "All versions compatible."
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_incompatible_with(self):
        log = "Mod A is incompatible with Mod B"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("版本冲突", combined)

    def test_incompatible_mod_versions(self):
        log = "Incompatible mod versions detected"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_version_mismatch(self):
        log = "Version mismatch: expected 1.0, found 2.0"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_duplicate_mod_found(self):
        log = "Duplicate mod found: somemod-1.0.jar"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_version_required_by(self):
        log = "Error: but version 1.18.2 is required by forge"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("版本冲突", combined)

    def test_incompatible_with_mod(self):
        log = "optifine is incompatible with mod sodium"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_conflict_details_extracted(self):
        log = "Mod optifine is incompatible with sodium"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("冲突详情", combined)

    def test_suggestion_included(self):
        log = "Mod A is incompatible with Mod B"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        combined = " ".join(r.message for r in results)
        self.assertIn("建议", combined)

    def test_get_patterns_cached(self):
        p1 = VersionConflictsDetector._get_patterns()
        p2 = VersionConflictsDetector._get_patterns()
        self.assertIs(p1, p2)

    def test_get_detail_patterns_cached(self):
        p1 = VersionConflictsDetector._get_detail_patterns()
        p2 = VersionConflictsDetector._get_detail_patterns()
        self.assertIs(p1, p2)

    def test_case_insensitive(self):
        log = "VERSION CONFLICT detected"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_mod_resolution_failed(self):
        log = "Mod resolution failed"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)


# ============================================================
# ShaderWorldConflictsDetector 测试 (任务 2.1 - shader_world_conflicts.py)
# ============================================================

class TestShaderWorldConflictsDetector(unittest.TestCase):
    """着色器与世界冲突检测器测试。"""

    def setUp(self):
        self.detector = ShaderWorldConflictsDetector()
        self.analyzer = MockAnalyzer()

    def test_metadata(self):
        self.assertEqual(self.detector.get_name(), "ShaderWorldConflictsDetector")
        self.assertIsNone(self.detector.get_cause_label())

    def test_empty_log(self):
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log="")
        results = self.detector.detect("", ctx)
        self.assertEqual(len(results), 0)

    def test_no_conflict_db(self):
        log = "Some shader mod loaded"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_blacklist_match_in_mods(self):
        self.analyzer.conflict_db = {
            "blacklist": [
                {"render": ["optifine"], "world": ["biomesoplenty"], "note": "已知冲突"}
            ]
        }
        self.analyzer.mods = {"optifine": "1.0", "biomesoplenty": "1.0"}
        log = "Crash report"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("不兼容", combined)

    def test_blacklist_match_in_log(self):
        self.analyzer.conflict_db = {
            "blacklist": [
                {"render": ["optifine"], "world": ["biomesoplenty"], "note": "已知冲突"}
            ]
        }
        self.analyzer.mods = {}
        log = "Crash caused by optifine and biomesoplenty"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)

    def test_whitelist_match(self):
        self.analyzer.conflict_db = {
            "whitelist": [
                {"render": ["iris"], "world": ["terralith"], "note": "兼容"}
            ]
        }
        self.analyzer.mods = {"iris": "1.0", "terralith": "1.0"}
        log = "Crash report"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("兼容", combined)

    def test_both_blacklist_and_whitelist(self):
        self.analyzer.conflict_db = {
            "blacklist": [
                {"render": ["optifine"], "world": ["biomesoplenty"], "note": "冲突"}
            ],
            "whitelist": [
                {"render": ["iris"], "world": ["terralith"], "note": "兼容"}
            ]
        }
        self.analyzer.mods = {"optifine": "1.0", "biomesoplenty": "1.0",
                              "iris": "1.0", "terralith": "1.0"}
        log = "Crash"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertTrue(len(results) > 0)
        combined = " ".join(r.message for r in results)
        self.assertIn("不兼容", combined)
        self.assertIn("兼容", combined)

    def test_partial_match_no_result(self):
        self.analyzer.conflict_db = {
            "blacklist": [
                {"render": ["optifine"], "world": ["biomesoplenty"], "note": "冲突"}
            ]
        }
        self.analyzer.mods = {"optifine": "1.0"}
        log = "Crash - only render mod present"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        self.assertEqual(len(results), 0)

    def test_duplicate_entries_skipped(self):
        self.analyzer.conflict_db = {
            "blacklist": [
                {"render": ["optifine"], "world": ["biomesoplenty"], "note": "冲突1"},
                {"render": ["optifine"], "world": ["biomesoplenty"], "note": "冲突2"},
            ]
        }
        self.analyzer.mods = {"optifine": "1.0", "biomesoplenty": "1.0"}
        log = "Crash"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        conflict_msgs = [r for r in results if "不兼容" in r.message and "映射" not in r.message]
        self.assertEqual(len(conflict_msgs), 1)

    def test_display_name_from_mods(self):
        self.analyzer.conflict_db = {
            "blacklist": [
                {"render": ["opti"], "world": ["biome"], "note": "冲突"}
            ]
        }
        self.analyzer.mods = {"OptiFine_HD_U": "1.0", "BiomesOPlenty": "1.0"}
        log = "Crash"
        ctx = AnalysisContext(analyzer=self.analyzer, crash_log=log)
        results = self.detector.detect(log, ctx)
        combined = " ".join(r.message for r in results)
        self.assertIn("OptiFine_HD_U", combined)
        self.assertIn("BiomesOPlenty", combined)


if __name__ == '__main__':
    unittest.main(verbosity=2)
