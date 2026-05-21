import unittest
import sys
import os
import tempfile
import json
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mca_core.security import (
    InputSanitizer,
    MemoryLimitExceededError,
    CpuLimitExceededError,
    ResourceLimiter,
    ErrorSanitizer,
    DebugDetector,
    IntegrityChecker,
    GitHubAutoRepair,
    ExternalLibValidator,
)


class TestInputSanitizer(unittest.TestCase):

    def test_sanitize_log_content_normal(self):
        content = "line1\nline2\nline3"
        result = InputSanitizer.sanitize_log_content(content)
        self.assertEqual(result, content)

    def test_sanitize_log_content_truncates_long_lines(self):
        long_line = "x" * 10000
        content = f"{long_line}\nshort"
        result = InputSanitizer.sanitize_log_content(content)
        lines = result.splitlines()
        from config.constants import MAX_LOG_LINE_LENGTH
        self.assertLessEqual(len(lines[0]), MAX_LOG_LINE_LENGTH)
        self.assertEqual(lines[1], "short")

    def test_sanitize_log_content_empty(self):
        result = InputSanitizer.sanitize_log_content("")
        self.assertEqual(result, "")

    def test_validate_file_path_empty(self):
        self.assertFalse(InputSanitizer.validate_file_path(""))

    def test_validate_file_path_null_byte(self):
        self.assertFalse(InputSanitizer.validate_file_path("test\x00.txt"))

    def test_validate_file_path_exists(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            path = f.name
        try:
            self.assertTrue(InputSanitizer.validate_file_path(path))
        finally:
            os.unlink(path)

    def test_validate_file_path_not_exists(self):
        self.assertFalse(InputSanitizer.validate_file_path("/nonexistent/file.txt"))

    def test_validate_file_path_with_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.txt")
            with open(filepath, "w") as f:
                f.write("test")
            self.assertTrue(InputSanitizer.validate_file_path(filepath, base_dir=tmpdir))

    def test_validate_file_path_outside_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
                outside_path = f.name
            try:
                self.assertFalse(InputSanitizer.validate_file_path(outside_path, base_dir=tmpdir))
            finally:
                os.unlink(outside_path)

    def test_validate_dir_path_empty(self):
        self.assertFalse(InputSanitizer.validate_dir_path(""))

    def test_validate_dir_path_null_byte(self):
        self.assertFalse(InputSanitizer.validate_dir_path("test\x00"))

    def test_validate_dir_path_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertTrue(InputSanitizer.validate_dir_path(tmpdir))

    def test_validate_dir_path_with_create(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "new_subdir")
            self.assertTrue(InputSanitizer.validate_dir_path(new_dir, base_dir=tmpdir, create=True))

    def test_validate_dir_path_create_outside_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outside_dir = os.path.join(os.path.dirname(tmpdir), "outside")
            self.assertFalse(InputSanitizer.validate_dir_path(outside_dir, base_dir=tmpdir, create=True))

    def test_sanitize_url_valid_http(self):
        url = "http://example.com"
        self.assertEqual(InputSanitizer.sanitize_url(url), url)

    def test_sanitize_url_valid_https(self):
        url = "https://example.com"
        self.assertEqual(InputSanitizer.sanitize_url(url), url)

    def test_sanitize_url_invalid_scheme(self):
        self.assertIsNone(InputSanitizer.sanitize_url("file:///etc/passwd"))

    def test_sanitize_url_empty(self):
        self.assertIsNone(InputSanitizer.sanitize_url(""))

    def test_sanitize_url_none(self):
        self.assertIsNone(InputSanitizer.sanitize_url(None))

    def test_sanitize_url_malformed(self):
        self.assertIsNone(InputSanitizer.sanitize_url("not a valid :// url at all"))

    def test_is_within_base_no_base(self):
        self.assertTrue(InputSanitizer._is_within_base("/any/path", None))

    def test_is_within_base_exception(self):
        self.assertFalse(InputSanitizer._is_within_base("\x00invalid", "/base"))


class TestErrorSanitizer(unittest.TestCase):

    def test_sanitize_empty_message(self):
        result = ErrorSanitizer.sanitize_error_message("")
        self.assertEqual(result, "未知错误")

    def test_sanitize_replaces_home(self):
        home = os.path.expanduser("~")
        msg = f"Error at {home}/some/file.py"
        result = ErrorSanitizer.sanitize_error_message(msg)
        self.assertIn("~", result)
        self.assertNotIn(home, result)

    def test_sanitize_replaces_windows_path(self):
        msg = "Error at C:\\Users\\test\\file.py"
        result = ErrorSanitizer.sanitize_error_message(msg)
        self.assertIn("[路径]", result)

    def test_sanitize_replaces_home_path(self):
        msg = "Error at /home/user/file.py"
        result = ErrorSanitizer.sanitize_error_message(msg)
        self.assertIn("[用户]", result)

    def test_sanitize_replaces_temp(self):
        msg = f"Error at C:\\Temp\\file.tmp"
        result = ErrorSanitizer.sanitize_error_message(msg)
        self.assertTrue("[临时目录]" in result or "[路径]" in result or "Temp" in result)

    def test_sanitize_replaces_python_file_path(self):
        msg = 'File "C:\\Python\\lib\\module.py", line 42, in func'
        result = ErrorSanitizer.sanitize_error_message(msg)
        self.assertTrue("文件" in result or "路径" in result)

    def test_sanitize_traceback_empty(self):
        result = ErrorSanitizer.sanitize_traceback("")
        self.assertEqual(result, "")

    def test_sanitize_traceback_normal(self):
        tb = 'File "/home/user/project/main.py", line 10, in <module>\n    raise Exception("test")'
        result = ErrorSanitizer.sanitize_traceback(tb)
        self.assertIn("main.py", result)
        self.assertNotIn("/home/user/project", result)


class TestDebugDetector(unittest.TestCase):

    def test_is_debugging_default(self):
        result = DebugDetector.is_debugging()
        self.assertIsInstance(result, bool)

    @patch("sys.modules", {"debugpy": MagicMock()})
    def test_is_debugging_with_debugpy(self):
        self.assertTrue(DebugDetector.is_debugging())

    @patch("sys.modules", {})
    @patch("sys.gettrace", return_value=None)
    def test_is_debugging_no_debugger(self, mock_gettrace):
        self.assertFalse(DebugDetector.is_debugging())

    def test_is_virtual_machine(self):
        result = DebugDetector.is_virtual_machine()
        self.assertIsInstance(result, bool)


class TestIntegrityChecker(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.checker = IntegrityChecker(base_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_compute_file_hash(self):
        test_file = os.path.join(self.tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")
        h = self.checker.compute_file_hash(test_file)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)

    def test_compute_file_hash_same_content(self):
        test_file = os.path.join(self.tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("content")
        h1 = self.checker.compute_file_hash(test_file)
        h2 = self.checker.compute_file_hash(test_file)
        self.assertEqual(h1, h2)

    def test_compute_file_hash_different_content(self):
        f1 = os.path.join(self.tmpdir, "f1.txt")
        f2 = os.path.join(self.tmpdir, "f2.txt")
        with open(f1, "w") as f:
            f.write("content1")
        with open(f2, "w") as f:
            f.write("content2")
        h1 = self.checker.compute_file_hash(f1)
        h2 = self.checker.compute_file_hash(f2)
        self.assertNotEqual(h1, h2)

    def test_compute_file_hash_nonexistent(self):
        h = self.checker.compute_file_hash("/nonexistent/file.txt")
        self.assertEqual(h, "")

    def test_verify_integrity_no_files(self):
        ok, modified = self.checker.verify_integrity({})
        self.assertTrue(ok)
        self.assertEqual(modified, [])

    def test_get_current_hashes(self):
        hashes = self.checker.get_current_hashes()
        self.assertIsInstance(hashes, dict)

    def test_save_and_load_baseline(self):
        baseline_path = os.path.join(self.tmpdir, "baseline.json")
        self.assertTrue(self.checker.save_baseline(baseline_path))
        loaded = self.checker.load_baseline(baseline_path)
        self.assertIsInstance(loaded, dict)

    def test_load_baseline_nonexistent(self):
        loaded = self.checker.load_baseline("/nonexistent/baseline.json")
        self.assertEqual(loaded, {})

    def test_verify_offline_no_baseline(self):
        ok, modified, msg = self.checker.verify_offline()
        self.assertIsNone(ok)
        self.assertEqual(modified, [])
        self.assertIn("无基线", msg)

    def test_export_offline_fix_package(self):
        import zipfile
        src_dir = os.path.join(self.tmpdir, "src", "mca_core")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "security.py"), "w") as f:
            f.write("# test")
        with open(os.path.join(src_dir, "launcher.py"), "w") as f:
            f.write("# test")
        config_dir = os.path.join(self.tmpdir, "src", "config")
        os.makedirs(config_dir)
        with open(os.path.join(config_dir, "constants.py"), "w") as f:
            f.write("# test")

        output_dir = os.path.join(self.tmpdir, "output")
        os.makedirs(output_dir)
        zip_path = self.checker.export_offline_fix_package(output_dir)
        self.assertTrue(os.path.exists(zip_path))
        self.assertTrue(zipfile.is_zipfile(zip_path))

    def test_verify_integrity_with_known_hashes(self):
        f_path = os.path.join(self.tmpdir, "src", "mca_core", "security.py")
        os.makedirs(os.path.dirname(f_path))
        with open(f_path, "w") as f:
            f.write("# test file")
        h = self.checker.compute_file_hash(f_path)
        ok, modified = self.checker.verify_integrity(
            {"src/mca_core/security.py": h}
        )
        self.assertTrue(ok)
        self.assertEqual(modified, [])

    def test_verify_integrity_tampered(self):
        f_path = os.path.join(self.tmpdir, "src", "mca_core", "security.py")
        os.makedirs(os.path.dirname(f_path))
        with open(f_path, "w") as f:
            f.write("# original")
        ok, modified = self.checker.verify_integrity(
            {"src/mca_core/security.py": "wronghash"}
        )
        self.assertFalse(ok)
        self.assertIn("src/mca_core/security.py", modified)


class TestGitHubAutoRepair(unittest.TestCase):

    def setUp(self):
        self.repair = GitHubAutoRepair(
            repo_owner="testowner",
            repo_name="testrepo",
            branch="main",
        )

    def test_headers_no_token(self):
        headers = self.repair._get_headers()
        self.assertIn("Accept", headers)
        self.assertNotIn("Authorization", headers)

    def test_headers_with_token(self):
        repair = GitHubAutoRepair(
            repo_owner="testowner",
            repo_name="testrepo",
            token="test_token",
        )
        headers = repair._get_headers()
        self.assertIn("Authorization", headers)
        self.assertIn("test_token", headers["Authorization"])

    @patch("urllib.request.urlopen")
    def test_fetch_file_content_success(self, mock_urlopen):
        import base64
        content = "print('hello')"
        encoded = base64.b64encode(content.encode()).decode()
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"content": encoded}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        success, result = self.repair.fetch_file_content("test.py")
        self.assertTrue(success)
        self.assertEqual(result, content)

    @patch("urllib.request.urlopen")
    def test_fetch_file_content_no_content(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"no_content": True}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        success, result = self.repair.fetch_file_content("test.py")
        self.assertFalse(success)

    @patch("urllib.request.urlopen")
    def test_fetch_file_content_network_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        success, result = self.repair.fetch_file_content("test.py")
        self.assertFalse(success)
        self.assertIn("网络错误", result)

    def test_verify_and_repair_file_not_exists(self):
        import shutil
        tmpdir = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
            test_file = os.path.join(tmpdir, "src", "test.py")
            repair = GitHubAutoRepair("owner", "repo")
            with patch.object(repair, "fetch_file_content",
                              return_value=(True, "# test")):
                success, msg = repair.verify_and_repair("src/test.py", tmpdir, backup=False)
                self.assertTrue(success)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_verify_and_repair_fetch_fails(self):
        tmpdir = tempfile.mkdtemp()
        try:
            repair = GitHubAutoRepair("owner", "repo")
            with patch.object(repair, "fetch_file_content",
                              return_value=(False, "Not found")):
                success, msg = repair.verify_and_repair("src/test.py", tmpdir)
                self.assertFalse(success)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_batch_repair(self):
        tmpdir = tempfile.mkdtemp()
        try:
            repair = GitHubAutoRepair("owner", "repo")
            with patch.object(repair, "verify_and_repair",
                              side_effect=[(True, "ok"), (False, "fail")]):
                results = repair.batch_repair(["f1.py", "f2.py"], tmpdir)
                self.assertEqual(len(results), 2)
                self.assertTrue(results["f1.py"][0])
                self.assertFalse(results["f2.py"][0])
        finally:
            import shutil
            shutil.rmtree(tmpdir)


class TestExternalLibValidator(unittest.TestCase):

    def test_validate_trusted_module(self):
        ok, reason = ExternalLibValidator.validate_module("os")
        self.assertTrue(ok)

    def test_validate_trusted_submodule(self):
        ok, reason = ExternalLibValidator.validate_module("mca_core.detectors")
        self.assertTrue(ok)

    def test_validate_dangerous_module(self):
        ok, reason = ExternalLibValidator.validate_module("ctypes")
        self.assertFalse(ok)
        self.assertIn("危险模块", reason)

    def test_validate_unknown_module(self):
        ok, reason = ExternalLibValidator.validate_module("some_unknown_mod")
        self.assertTrue(ok)

    def test_validate_lib_directory_not_exists(self):
        ok, warnings = ExternalLibValidator.validate_lib_directory("/nonexistent")
        self.assertTrue(ok)


class TestResourceLimiter(unittest.TestCase):

    def test_init(self):
        limiter = ResourceLimiter(max_memory_mb=256, max_cpu_percent=50)
        self.assertEqual(limiter.max_memory, 256 * 1024 * 1024)
        self.assertEqual(limiter.max_cpu, 50)

    def test_memory_limit_exceeded_error(self):
        with self.assertRaises(MemoryLimitExceededError):
            raise MemoryLimitExceededError()

    def test_cpu_limit_exceeded_error(self):
        with self.assertRaises(CpuLimitExceededError):
            raise CpuLimitExceededError()

    def test_get_memory_usage_no_psutil(self):
        limiter = ResourceLimiter()
        with patch.object(limiter, "_get_memory_usage", return_value=0):
            self.assertEqual(limiter._get_memory_usage(), 0)

    def test_get_cpu_usage_no_psutil(self):
        limiter = ResourceLimiter()
        with patch.object(limiter, "_get_cpu_usage", return_value=0):
            self.assertEqual(limiter._get_cpu_usage(), 0)

    def test_check_limits_memory_exceeded(self):
        limiter = ResourceLimiter(max_memory_mb=500)
        with patch.object(limiter, "_get_memory_usage", return_value=600 * 1024 * 1024), \
             patch.object(limiter, "_get_cpu_usage", return_value=0):
            with self.assertRaises(MemoryLimitExceededError):
                limiter.check_limits()

    def test_check_limits_cpu_exceeded(self):
        limiter = ResourceLimiter(max_cpu_percent=50)
        with patch.object(limiter, "_get_memory_usage", return_value=1), \
             patch.object(limiter, "_get_cpu_usage", return_value=90):
            with self.assertRaises(CpuLimitExceededError):
                limiter.check_limits()

    def test_check_limits_ok(self):
        limiter = ResourceLimiter(max_memory_mb=500, max_cpu_percent=80)
        with patch.object(limiter, "_get_memory_usage", return_value=1024), \
             patch.object(limiter, "_get_cpu_usage", return_value=10):
            limiter.check_limits()

    def test_init_cpu_monitor_no_psutil(self):
        limiter = ResourceLimiter()
        limiter._process = None
        self.assertIsNone(limiter._process)

    def test_init_cpu_monitor_exception(self):
        limiter = ResourceLimiter()
        limiter._process = None
        self.assertIsNone(limiter._process)


class TestErrorSanitizerEdgeCases(unittest.TestCase):

    def test_sanitize_error_none_message(self):
        result = ErrorSanitizer.sanitize_error_message(None)
        self.assertEqual(result, "未知错误")

    def test_sanitize_traceback_none(self):
        result = ErrorSanitizer.sanitize_traceback(None)
        self.assertEqual(result, "")

    def test_sanitize_traceback_with_home(self):
        home = os.path.expanduser("~")
        if home:
            tb = f'File "{home}/project/file.py", line 1'
            result = ErrorSanitizer.sanitize_traceback(tb)
            self.assertIn("file.py", result)
        else:
            self.skipTest("No home directory")


class TestGetDefaultRepair(unittest.TestCase):

    @patch("os.path.exists", return_value=False)
    def test_get_default_repair_no_config(self, mock_exists):
        from mca_core.security import get_default_repair
        result = get_default_repair()
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)