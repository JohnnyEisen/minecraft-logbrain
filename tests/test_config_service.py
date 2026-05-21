"""测试配置服务 — 补全 config_service 覆盖率到100%。"""
import json
import os
import shutil
import tempfile
import pytest
from src.mca_core.services.config_service import ConfigService


class TestConfigServiceFull:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "cfg.json")
        self.svc = ConfigService(self.config_path)
        yield
        shutil.rmtree(self.test_dir)

    def test_defaults(self):
        assert self.svc.get_scroll_sensitivity() == 6
        assert self.svc.get_highlight_size_limit() == 300_000

    def test_setters(self):
        self.svc.set_scroll_sensitivity(10)
        self.svc.set_highlight_size_limit(50000)
        assert self.svc.get_scroll_sensitivity() == 10
        assert self.svc.get_highlight_size_limit() == 50000

    def test_save_creates_file(self):
        self.svc.set_scroll_sensitivity(8)
        self.svc.save()
        assert os.path.exists(self.config_path)

    def test_save_writes_json(self):
        self.svc.set_scroll_sensitivity(3)
        self.svc.set_highlight_size_limit(999)
        self.svc.save()
        with open(self.config_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["scroll_sensitivity"] == 3
        assert data["highlight_size_limit"] == 999

    def test_save_and_reload(self):
        self.svc.set_scroll_sensitivity(5)
        self.svc.set_highlight_size_limit(200000)
        self.svc.save()
        new_svc = ConfigService(self.config_path)
        assert new_svc.get_scroll_sensitivity() == 5
        assert new_svc.get_highlight_size_limit() == 200000

    def test_load_existing_file(self):
        data = {"scroll_sensitivity": 7, "highlight_size_limit": 123456}
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        svc = ConfigService(self.config_path)
        assert svc.get_scroll_sensitivity() == 7
        assert svc.get_highlight_size_limit() == 123456

    def test_load_corrupted_json_falls_back_to_defaults(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("not valid json {{{")
        svc = ConfigService(self.config_path)
        assert svc.get_scroll_sensitivity() == 6

    def test_load_partial_json(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"scroll_sensitivity": 9}, f)
        svc = ConfigService(self.config_path)
        assert svc.get_scroll_sensitivity() == 9
        assert svc.get_highlight_size_limit() == 300_000

    def test_multiple_saves(self):
        self.svc.set_scroll_sensitivity(1)
        self.svc.save()
        self.svc.set_scroll_sensitivity(2)
        self.svc.save()
        data = json.load(open(self.config_path, encoding="utf-8"))
        assert data["scroll_sensitivity"] == 2

    def test_save_permission_error_handled(self, monkeypatch):
        self.svc.set_scroll_sensitivity(1)
        original_open = open
        def mock_open(path, mode, **kw):
            if "cfg.json" in str(path) and "w" in mode:
                raise PermissionError("denied")
            return original_open(path, mode, **kw)
        monkeypatch.setattr("builtins.open", mock_open)
        self.svc.save()
        # Should not raise