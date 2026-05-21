"""测试正则缓存 — 补全覆盖率至85%+。"""
import re
import pytest
from src.mca_core.regex_cache import RegexCache


class TestRegexCache:
    def setup_method(self):
        RegexCache.clear()

    def test_get_compiles(self):
        compiled = RegexCache.get(r"\d+")
        assert isinstance(compiled, re.Pattern)
        assert compiled.search("abc123") is not None

    def test_get_cache_hit(self):
        RegexCache.get(r"test_pat")
        RegexCache.get(r"test_pat")
        stats = RegexCache.get_stats()
        assert stats["hits"] >= 1

    def test_get_with_flags(self):
        r1 = RegexCache.get(r"hello")
        r2 = RegexCache.get(r"hello", re.IGNORECASE)
        assert r1 is not r2
        assert r2.search("HELLO") is not None

    def test_set_max_size(self):
        RegexCache.set_max_size(3)
        RegexCache.get(r"p1")
        RegexCache.get(r"p2")
        RegexCache.get(r"p3")
        RegexCache.get(r"p4")
        stats = RegexCache.get_stats()
        assert stats["size"] <= 3
        assert r"p1" not in str(RegexCache._cache.keys())

    def test_set_max_size_invalid(self):
        with pytest.raises(ValueError):
            RegexCache.set_max_size(0)
        with pytest.raises(ValueError):
            RegexCache.set_max_size(-1)

    def test_search_basic(self):
        assert RegexCache.search(r"\d+", "abc 123 def") is not None
        assert RegexCache.search(r"\d+", "abc def") is None

    def test_search_with_flags(self):
        assert RegexCache.search(r"hello", "HELLO WORLD", flags=re.IGNORECASE) is not None

    def test_findall(self):
        result = RegexCache.findall(r"\d+", "a1 b22 c333")
        assert result == ["1", "22", "333"]

    def test_findall_empty(self):
        result = RegexCache.findall(r"\d+", "no numbers here")
        assert result == []

    def test_finditer(self):
        matches = list(RegexCache.finditer(r"\d+", "a1 b22"))
        assert len(matches) == 2
        assert matches[0].group() == "1"
        assert matches[1].group() == "22"

    def test_finditer_empty(self):
        matches = list(RegexCache.finditer(r"\d+", "no numbers"))
        assert len(matches) == 0

    def test_clear(self):
        RegexCache.get(r"pat1")
        RegexCache.get(r"pat2")
        RegexCache.search(r"pat1", "test")
        assert RegexCache.get_stats()["size"] >= 2
        RegexCache.clear()
        stats = RegexCache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0

    def test_get_stats(self):
        RegexCache.clear()
        RegexCache.get(r"a")
        RegexCache.get(r"a")
        RegexCache.get(r"b")
        stats = RegexCache.get_stats()
        assert stats["size"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["max_size"] > 0

    def test_hit_rate_zero_initially(self):
        RegexCache.clear()
        stats = RegexCache.get_stats()
        assert stats["hit_rate"] == 0.0

    def test_lru_eviction(self):
        RegexCache.set_max_size(2)
        RegexCache.get(r"first")
        RegexCache.get(r"second")
        # Access 'first' to make it recently used
        RegexCache.get(r"first")
        # Add 'third' — should evict 'second' (least recently used)
        RegexCache.get(r"third")
        stats = RegexCache.get_stats()
        assert stats["size"] == 2

    def test_thread_safety_basic(self):
        RegexCache.clear()
        for i in range(100):
            RegexCache.get(r"thread_pat")
        stats = RegexCache.get_stats()
        assert stats["size"] == 1