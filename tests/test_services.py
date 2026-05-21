import unittest
import sys
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

# Ensure root dir is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mca_core.services.config_service import ConfigService
from mca_core.services.system_service import SystemService
from config.app_config import AppConfig

class TestConfigService(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "test_config.json")
        self.service = ConfigService(self.config_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_default_values(self):
        # Should use defaults when file doesn't exist
        # DEFAULT_SCROLL_SENSITIVITY is 6 in constants.py (defined twice, last one wins)
        self.assertEqual(self.service.get_scroll_sensitivity(), 6)
        # HIGHLIGHT_SIZE_LIMIT is 300_000 in constants.py
        self.assertEqual(self.service.get_highlight_size_limit(), 300000)

    def test_save_and_load(self):
        self.service.set_scroll_sensitivity(5)
        self.service.set_highlight_size_limit(100)
        self.service.save()

        # Create new service instance to load from file
        new_service = ConfigService(self.config_path)
        self.assertEqual(new_service.get_scroll_sensitivity(), 5)
        self.assertEqual(new_service.get_highlight_size_limit(), 100)

class TestSystemService(unittest.TestCase):
    def setUp(self):
        self.service = SystemService()

    def test_get_system_info_structure(self):
        info = self.service.get_system_info()
        self.assertIn('platform', info)
        self.assertIn('python', info)
        
    @patch('mca_core.services.system_service.platform')
    def test_cached_info(self, mock_platform):
        mock_platform.platform.return_value = "MockOS"
        mock_platform.python_version.return_value = "3.9.9"
        
        info1 = self.service.get_system_info()
        self.assertEqual(info1['platform'], "MockOS")
        
        mock_platform.platform.return_value = "ChangedOS"
        info2 = self.service.get_system_info()
        self.assertEqual(info2['platform'], "MockOS")

    def test_clear_cache(self):
        self.service._cached_info = {"platform": "cached", "python": "3.9"}
        self.service.clear_cache()
        self.assertIsNone(self.service._cached_info)

    def test_get_system_info_after_clear(self):
        self.service._cached_info = {"platform": "old", "python": "3.9"}
        self.service.clear_cache()
        info = self.service.get_system_info()
        self.assertIsNotNone(info)
        self.assertIn("platform", info)

    @patch('mca_core.services.system_service.platform')
    def test_collect_platform_info_exception(self, mock_platform):
        mock_platform.platform.side_effect = Exception("platform error")
        mock_platform.python_version.side_effect = Exception("version error")
        info = self.service._collect_info()
        self.assertIsInstance(info, dict)

    @patch('mca_core.services.system_service.platform')
    def test_collect_cpu_memory_no_psutil(self, mock_platform):
        mock_platform.platform.return_value = "TestOS"
        mock_platform.python_version.return_value = "3.9"
        import builtins
        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == 'psutil':
                raise ImportError("No module named 'psutil'")
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=mock_import):
            self.service.clear_cache()
            info = self.service.get_system_info()
            self.assertIn("platform", info)
            self.assertEqual(info["platform"], "TestOS")

    @patch('mca_core.services.system_service.platform')
    def test_collect_cpu_memory_psutil_error(self, mock_platform):
        mock_platform.platform.return_value = "TestOS"
        mock_platform.python_version.return_value = "3.9"
        mock_psutil = MagicMock()
        mock_psutil.cpu_count.side_effect = Exception("psutil error")
        with patch.dict('sys.modules', {'psutil': mock_psutil}):
            self.service.clear_cache()
            info = self.service._collect_info()
            self.assertIn("platform", info)

    @patch('mca_core.services.system_service.platform')
    def test_collect_gpu_no_gputil(self, mock_platform):
        mock_platform.platform.return_value = "TestOS"
        mock_platform.python_version.return_value = "3.9"
        import builtins
        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == 'GPUtil':
                raise ImportError("No module named 'GPUtil'")
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=mock_import):
            self.service.clear_cache()
            info = self.service.get_system_info()
            self.assertIn("platform", info)

    @patch('mca_core.services.system_service.platform')
    def test_collect_gpu_gputil_error(self, mock_platform):
        mock_platform.platform.return_value = "TestOS"
        mock_platform.python_version.return_value = "3.9"
        mock_gputil = MagicMock()
        mock_gputil.getGPUs.side_effect = Exception("GPU error")
        with patch.dict('sys.modules', {'GPUtil': mock_gputil}):
            self.service.clear_cache()
            info = self.service._collect_info()
            self.assertIn("platform", info)

    @patch('mca_core.services.system_service.platform')
    def test_psutil_not_installed_handled(self, mock_platform):
        mock_platform.platform.return_value = "TestOS"
        mock_platform.python_version.return_value = "3.9"
        import builtins
        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == 'psutil':
                raise ImportError("No module named 'psutil'")
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=mock_import):
            self.service.clear_cache()
            info = self.service._collect_info()
            self.assertIn("platform", info)

    @patch('mca_core.services.system_service.platform')
    def test_gputil_not_installed_handled(self, mock_platform):
        mock_platform.platform.return_value = "TestOS"
        mock_platform.python_version.return_value = "3.9"
        import builtins
        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == 'GPUtil':
                raise ImportError("No module named 'GPUtil'")
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=mock_import):
            self.service.clear_cache()
            info = self.service._collect_info()
            self.assertIn("platform", info)

if __name__ == '__main__':
    unittest.main()
