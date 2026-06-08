import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mca_core.diagnostic_engine import DiagnosticEngine


class TestDiagnosticEngine(unittest.TestCase):
    """诊断引擎基础测试，防止 Optional 等导入问题回归。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = self.temp_dir.name
        self.engine = DiagnosticEngine(self.data_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_creates_instance(self):
        self.assertIsNotNone(self.engine)
        self.assertEqual(self.engine.data_dir, self.data_dir)
        self.assertIsNotNone(self.engine.repo)
        self.assertIsNotNone(self.engine.rules)

    def test_default_rules_loaded(self):
        rules = self.engine.rules
        self.assertIn("patterns", rules)
        patterns = rules["patterns"]
        self.assertIsInstance(patterns, list)
        self.assertGreater(len(patterns), 0)
        pattern_ids = [p["id"] for p in patterns]
        self.assertIn("out_of_memory", pattern_ids)
        self.assertIn("missing_dependency", pattern_ids)
        self.assertIn("mixin_conflict", pattern_ids)
        self.assertIn("version_conflict", pattern_ids)
        self.assertIn("gl_error", pattern_ids)

    def test_compute_log_hash_deterministic(self):
        h1 = self.engine._compute_log_hash("test crash log")
        h2 = self.engine._compute_log_hash("test crash log")
        self.assertEqual(h1, h2)

    def test_compute_log_hash_different_for_different_inputs(self):
        h1 = self.engine._compute_log_hash("test crash log A")
        h2 = self.engine._compute_log_hash("test crash log B")
        self.assertNotEqual(h1, h2)

    def test_analyze_out_of_memory(self):
        log = "[main/WARN]: java.lang.OutOfMemoryError: Java heap space"
        results = self.engine.analyze(log)
        self.assertIsInstance(results, list)
        found = any(r["type"] in ("out_of_memory", "内存溢出") for r in results)
        self.assertTrue(found, "应检测到 OutOfMemoryError")

    def test_analyze_missing_dependency(self):
        log = "Missing mod examplemod is required"
        results = self.engine.analyze(log)
        found = any(r["type"] in ("missing_dependency", "缺失依赖") for r in results)
        self.assertTrue(found, "应检测到缺失依赖")

    def test_analyze_no_match_returns_empty(self):
        log = "Nothing relevant here"
        results = self.engine.analyze(log)
        self.assertEqual(results, [])

    def test_analyze_result_structure(self):
        log = "Exception in thread \"main\" Initialization failed"
        results = self.engine.analyze(log)
        for r in results:
            self.assertIn("type", r)
            self.assertIn("name", r)
            self.assertIn("diagnosis", r)
            self.assertIn("solutions", r)

    def test_learn_solution(self):
        self.engine.learn_solution("test_sig", "restart the game")
        self.assertEqual(len(self.engine.learning_data["user_solutions"]), 1)
        self.assertEqual(
            self.engine.learning_data["user_solutions"][0]["signature"],
            "test_sig"
        )

    def test_cache_hit(self):
        log = "OutOfMemoryError: Metaspace"
        results1 = self.engine.analyze(log)
        results2 = self.engine.analyze(log)
        self.assertEqual(len(results1), len(results2))

    def test_empty_log(self):
        results = self.engine.analyze("")
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()