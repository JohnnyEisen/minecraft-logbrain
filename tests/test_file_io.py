"""测试文件IO工具 — 补全覆盖率至85%+。"""
import os
import tempfile
import pytest
from src.mca_core.file_io import (
    read_text_stream,
    iter_lines,
    read_text_limited,
    read_text_head,
    read_with_backup,
    write_atomic,
    SafeFileOperator,
    DEFAULT_MAX_BYTES,
    MAX_FILE_SIZE_HARD_LIMIT,
)


class TestReadTextStream:
    def test_yields_chunks(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("hello world")
            path = f.name
        try:
            chunks = list(read_text_stream(path, chunk_size=3))
            assert all(isinstance(c, str) for c in chunks)
            assert "".join(chunks) == "hello world"
        finally:
            os.unlink(path)

    def test_nonexistent_raises(self):
        with pytest.raises(OSError):
            list(read_text_stream("/nonexistent/file.txt"))


class TestIterLines:
    def test_normal(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("a\nb\nc")
            path = f.name
        try:
            lines = list(iter_lines(path))
            assert lines[0].rstrip("\n") == "a"
            assert lines[1].rstrip("\n") == "b"
            assert lines[2].rstrip("\n") == "c"
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            lines = list(iter_lines(path))
            assert lines == []
        finally:
            os.unlink(path)

    def test_trailing_newline(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("x\ny\n")
            path = f.name
        try:
            lines = list(iter_lines(path))
            assert lines[0].rstrip("\n") == "x"
            assert lines[1].rstrip("\n") == "y"
        finally:
            os.unlink(path)

    def test_nonexistent_raises(self):
        with pytest.raises(OSError):
            list(iter_lines("/nonexistent.txt"))


class TestReadTextLimited:
    def test_small_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("small")
            path = f.name
        try:
            result = read_text_limited(path)
            assert result == "small"
        finally:
            os.unlink(path)

    def test_large_truncated(self):
        content = "x" * (DEFAULT_MAX_BYTES + 1000)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write(content)
            path = f.name
        try:
            result = read_text_limited(path)
            assert len(result) <= DEFAULT_MAX_BYTES + 500
        finally:
            os.unlink(path)

    def test_over_hard_limit(self):
        path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.seek(MAX_FILE_SIZE_HARD_LIMIT + 1)
            f.write(b"x")
            path = f.name
        try:
            with pytest.raises(ValueError):
                read_text_limited(path)
        finally:
            if path:
                os.unlink(path)


class TestReadTextHead:
    def test_normal(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("first\n" * 50)
            path = f.name
        try:
            result = read_text_head(path, max_bytes=100)
            assert len(result) <= 100
            assert "first" in result
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            result = read_text_head(path)
            assert result == ""
        finally:
            os.unlink(path)

    def test_oversize_file_returns_empty(self):
        path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.seek(MAX_FILE_SIZE_HARD_LIMIT + 1)
            f.write(b"x")
            path = f.name
        try:
            result = read_text_head(path)
            assert result == ""
        finally:
            if path:
                os.unlink(path)


class TestReadWithBackup:
    def test_primary_exists(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("primary")
            primary = f.name
        try:
            result = read_with_backup(primary)
            assert result == "primary"
        finally:
            os.unlink(primary)

    def test_fallback_to_backup(self):
        primary = tempfile.mktemp(suffix=".txt")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("backup_data")
            bak = f.name
        try:
            # Create .bak1 file at primary's expected backup location
            import shutil
            shutil.copy(bak, primary + ".bak1")
            result = read_with_backup(primary)
            assert result == "backup_data"
        finally:
            if os.path.exists(primary):
                os.unlink(primary)
            if os.path.exists(primary + ".bak1"):
                os.unlink(primary + ".bak1")
            os.unlink(bak)

    def test_both_missing(self):
        result = read_with_backup("/no/primary.txt")
        assert result is None


class TestWriteAtomic:
    def test_normal(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            write_atomic(path, "hello")
            with open(path, encoding="utf-8") as f:
                assert f.read() == "hello"
        finally:
            os.unlink(path)

    def test_overwrite(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("old")
            path = f.name
        try:
            write_atomic(path, "new")
            with open(path, encoding="utf-8") as f:
                assert f.read() == "new"
        finally:
            os.unlink(path)

    def test_unicode(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            write_atomic(path, "\u4e2d\u6587\u2603test")
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "\u2603" in content
        finally:
            os.unlink(path)


class TestSafeFileOperator:
    def test_read_with_backup(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
            f.write("safe_data")
            path = f.name
        try:
            result = SafeFileOperator.read_with_backup(path)
            assert result == "safe_data"
        finally:
            os.unlink(path)

    def test_write_atomic(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            SafeFileOperator.write_atomic(path, "atomic")
            with open(path, encoding="utf-8") as f:
                assert f.read() == "atomic"
        finally:
            os.unlink(path)