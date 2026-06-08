import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mca_core.services.log_service import LogService


class TestLogService(unittest.TestCase):
    def setUp(self):
        self.service = LogService()
        self.sample_log = "Line 1\nLine 2\nError: NullPointerException"

    def test_set_and_get_text(self):
        self.service.set_log_text(self.sample_log)
        self.assertEqual(self.service.get_text(), self.sample_log)

    def test_get_lower(self):
        self.service.set_log_text(self.sample_log)
        expected = self.sample_log.lower()
        self.assertEqual(self.service.get_lower(), expected)
        self.assertEqual(self.service.get_lower(), expected)

    def test_get_lines(self):
        self.service.set_log_text(self.sample_log)
        lines = self.service.get_lines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[2], "Error: NullPointerException")

    def test_get_lines_lower(self):
        self.service.set_log_text(self.sample_log)
        lines = self.service.get_lines(lower=True)
        self.assertEqual(lines[2], "error: nullpointerexception")

    def test_cache_invalidation(self):
        self.service.set_log_text("Old")
        self.assertEqual(self.service.get_lower(), "old")

        self.service.set_log_text("New")
        self.assertEqual(self.service.get_lower(), "new")
        self.assertEqual(self.service.get_lines()[0], "New")

    def test_lower_cache_reuse(self):
        self.service.set_log_text(self.sample_log)
        r1 = self.service.get_lines(lower=True)
        r2 = self.service.get_lines(lower=True)
        self.assertEqual(r1, r2)

    def test_normal_cache_reuse(self):
        self.service.set_log_text(self.sample_log)
        r1 = self.service.get_lines(lower=False)
        r2 = self.service.get_lines(lower=False)
        self.assertEqual(r1, r2)

    def test_alternating_cache_switch(self):
        self.service.set_log_text("ABC\nDef")
        normal = self.service.get_lines(lower=False)
        lower = self.service.get_lines(lower=True)
        self.assertEqual(normal[0], "ABC")
        self.assertEqual(lower[0], "abc")
        normal2 = self.service.get_lines(lower=False)
        lower2 = self.service.get_lines(lower=True)
        self.assertEqual(normal2[0], "ABC")
        self.assertEqual(lower2[0], "abc")

    def test_empty_log(self):
        self.service.set_log_text("")
        lines = self.service.get_lines()
        self.assertEqual(lines, [])
        lower_lines = self.service.get_lines(lower=True)
        self.assertEqual(lower_lines, [])

    def test_large_log_caching_performance(self):
        big = "\n".join(f"Line {i} with SOME Upper" for i in range(10000))
        self.service.set_log_text(big)
        self.service.get_lines(lower=True)
        import time
        t0 = time.monotonic()
        for _ in range(100):
            self.service.get_lines(lower=True)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 1.0, "Cached get_lines(lower=True) should be fast (<1s for 100 calls)")


if __name__ == '__main__':
    unittest.main()
