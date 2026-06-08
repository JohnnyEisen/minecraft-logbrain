from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from mca_core.analysis_engine import load_gpu_rules


class TestLoadGpuRules(unittest.TestCase):
    def setUp(self):
        from mca_core import analysis_engine
        analysis_engine._gpu_rules_cache = None

    def tearDown(self):
        from mca_core import analysis_engine
        analysis_engine._gpu_rules_cache = None

    def test_returns_empty_when_no_file(self):
        with patch("mca_core.analysis_engine.GPU_ISSUES_FILE", "/nonexistent/path"):
            result = load_gpu_rules()
            self.assertEqual(result, {})

    def test_loads_valid_json(self):
        data = {"nvidia": {"issues": ["black screen"]}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            with patch("mca_core.analysis_engine.GPU_ISSUES_FILE", path):
                result = load_gpu_rules()
                self.assertIn("nvidia", result)
        finally:
            os.unlink(path)

    def test_caches_result(self):
        with patch("mca_core.analysis_engine.GPU_ISSUES_FILE", "/nonexistent/path"):
            r1 = load_gpu_rules()
            r2 = load_gpu_rules()
            self.assertEqual(r1, r2)

    def test_handles_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json{{{")
            path = f.name
        try:
            with patch("mca_core.analysis_engine.GPU_ISSUES_FILE", path):
                result = load_gpu_rules()
                self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_handles_non_dict_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([1, 2, 3], f)
            path = f.name
        try:
            with patch("mca_core.analysis_engine.GPU_ISSUES_FILE", path):
                result = load_gpu_rules()
                self.assertEqual(result, {})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
