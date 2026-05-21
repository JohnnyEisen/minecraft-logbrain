"""测试导出器模块 — 覆盖所有导出格式。"""
import json
import os
import tempfile
import pytest
from src.mca_core.exporters import (
    AnalysisReport,
    HTMLExporter,
    MarkdownExporter,
    JSONExporter,
    PDFExporter,
    ReportExporter,
    UnsupportedFormatError,
)


class TestAnalysisReport:
    def test_create_report(self):
        r = AnalysisReport("title", "content")
        assert r.title == "title"
        assert r.content == "content"

    def test_empty_report(self):
        r = AnalysisReport("", "")
        assert r.title == ""
        assert r.content == ""


class TestHTMLExporter:
    def test_export_basic(self):
        r = AnalysisReport("Test", "Hello World")
        e = HTMLExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "<title>Test</title>" in content
            assert "Hello World" in content
            assert "<html>" in content
        finally:
            os.unlink(path)

    def test_export_special_chars(self):
        r = AnalysisReport("T&t", "x < y && z > w")
        e = HTMLExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "T&t" in content
            assert "x < y" in content
        finally:
            os.unlink(path)

    def test_export_writes_file(self):
        r = AnalysisReport("T", "c")
        e = HTMLExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            content = open(path).read()
            assert "<html>" in content
        finally:
            os.unlink(path)


class TestMarkdownExporter:
    def test_export_basic(self):
        r = AnalysisReport("MD Title", "MD Content")
        e = MarkdownExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "# MD Title" in content
            assert "MD Content" in content
        finally:
            os.unlink(path)

    def test_export_empty(self):
        r = AnalysisReport("", "")
        e = MarkdownExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            assert "# \n\n\n" == content
        finally:
            os.unlink(path)


class TestJSONExporter:
    def test_export_basic(self):
        r = AnalysisReport("J Title", "J Content")
        e = JSONExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["title"] == "J Title"
            assert data["content"] == "J Content"
        finally:
            os.unlink(path)

    def test_export_unicode(self):
        r = AnalysisReport("中文标题", "内容：\u2603测试")
        e = JSONExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["title"] == "中文标题"
            assert "☃" in data["content"]
        finally:
            os.unlink(path)

    def test_export_empty(self):
        r = AnalysisReport("", "")
        e = JSONExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data == {"title": "", "content": ""}
        finally:
            os.unlink(path)


class TestPDFExporter:
    def test_export_basic(self):
        r = AnalysisReport("PDF Test", "Line1\nLine2")
        e = PDFExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", mode="w") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, "rb") as f:
                content = f.read()
            assert content.startswith(b"%PDF-1.4")
            assert b"BT" in content
            assert b"ET" in content
            assert b"%%EOF" in content
        finally:
            os.unlink(path)

    def test_export_clips_to_50_lines(self):
        lines = [f"line{i}" for i in range(100)]
        r = AnalysisReport("Big", "\n".join(lines))
        e = PDFExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", mode="w") as f:
            path = f.name
        try:
            e.export(r, path)
            with open(path, "rb") as f:
                content = f.read()
            assert b"line0" in content
            assert b"line49" in content
            assert b"line50" not in content
        finally:
            os.unlink(path)

    def test_export_escapes_parens(self):
        r = AnalysisReport("T", "(paren)\n\\(slash)")
        e = PDFExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", mode="w") as f:
            path = f.name
        try:
            e.export(r, path)
            content = open(path, "rb").read()
            assert b"\\(" in content
            assert b"\\)" in content
        finally:
            os.unlink(path)


class TestReportExporter:
    def test_export_html(self):
        r = AnalysisReport("X", "Y")
        e = ReportExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, "html", path)
            content = open(path, encoding="utf-8").read()
            assert "<html>" in content
        finally:
            os.unlink(path)

    def test_export_json(self):
        r = AnalysisReport("A", "B")
        e = ReportExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, "json", path)
            data = json.load(open(path, encoding="utf-8"))
            assert data["title"] == "A"
        finally:
            os.unlink(path)

    def test_export_markdown(self):
        r = AnalysisReport("MD", "content")
        e = ReportExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as f:
            path = f.name
        try:
            e.export(r, "markdown", path)
            content = open(path, encoding="utf-8").read()
            assert "# MD" in content
        finally:
            os.unlink(path)

    def test_export_pdf(self):
        r = AnalysisReport("P", "line")
        e = ReportExporter()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", mode="w") as f:
            path = f.name
        try:
            e.export(r, "pdf", path)
            content = open(path, "rb").read()
            assert content.startswith(b"%PDF-1.4")
        finally:
            os.unlink(path)

    def test_unsupported_format(self):
        r = AnalysisReport("X", "Y")
        e = ReportExporter()
        with pytest.raises(UnsupportedFormatError) as exc_info:
            e.export(r, "docx", "/tmp/fake.docx")
        assert "docx" in str(exc_info.value)

    def test_unsupported_format_inherits_app_error(self):
        from src.mca_core.errors import AppError
        assert issubclass(UnsupportedFormatError, AppError)