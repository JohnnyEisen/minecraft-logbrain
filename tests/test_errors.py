"""测试错误处理模块 — 覆盖所有异常类和工具函数。"""
import pytest
from src.mca_core.errors import (
    AppError,
    UserError,
    SystemError,
    AnalysisError,
    TaskCancelledError,
    ConfigurationError,
    DependencyError,
    ErrorRecord,
    ErrorCollector,
    error_handler,
    safe_call,
    error_context,
)


class TestAppError:
    def test_basic(self):
        e = AppError("msg")
        assert e.message == "msg"
        assert e.code == "UNKNOWN"
        assert e.details == {}
        assert e.recoverable is False

    def test_full_args(self):
        e = AppError("msg", code="E001", details={"key": "val"}, recoverable=True)
        assert e.code == "E001"
        assert e.details == {"key": "val"}
        assert e.recoverable is True

    def test_to_dict(self):
        e = AppError("msg", code="E001")
        d = e.to_dict()
        assert d["type"] == "AppError"
        assert d["message"] == "msg"
        assert d["code"] == "E001"
        assert "timestamp" in d

    def test_is_exception(self):
        e = AppError("msg")
        assert isinstance(e, Exception)

    def test_str(self):
        e = AppError("hello")
        assert str(e) == "hello"


class TestUserError:
    def test_recoverable(self):
        e = UserError("user error")
        assert e.recoverable is True

    def test_inherits_app_error(self):
        e = UserError("x")
        assert isinstance(e, AppError)

    def test_to_dict(self):
        e = UserError("x", code="E100")
        d = e.to_dict()
        assert d["type"] == "UserError"
        assert d["recoverable"] is True


class TestSystemError:
    def test_not_recoverable(self):
        e = SystemError("system error")
        assert e.recoverable is False

    def test_inherits_app_error(self):
        e = SystemError("x")
        assert isinstance(e, AppError)


class TestAnalysisError:
    def test_basic(self):
        e = AnalysisError("analysis failed")
        assert e.recoverable is True
        assert isinstance(e, AppError)

    def test_with_detector(self):
        e = AnalysisError("failed", detector_name="my_detector")
        assert e.details["detector"] == "my_detector"

    def test_without_detector(self):
        e = AnalysisError("failed")
        assert "detector" not in e.details


class TestTaskCancelledError:
    def test_defaults(self):
        e = TaskCancelledError()
        assert e.message == "Task was cancelled"
        assert e.code == "CANCELLED"
        assert e.recoverable is True

    def test_with_task_id(self):
        e = TaskCancelledError(task_id="task-42")
        assert e.details["task_id"] == "task-42"

    def test_custom_message(self):
        e = TaskCancelledError("custom cancel")
        assert e.message == "custom cancel"


class TestConfigurationError:
    def test_basic(self):
        e = ConfigurationError("bad config")
        assert e.code == "CONFIG_ERROR"
        assert e.recoverable is True

    def test_with_key(self):
        e = ConfigurationError("bad", config_key="key1")
        assert e.details["config_key"] == "key1"


class TestDependencyError:
    def test_basic(self):
        e = DependencyError("missing dep")
        assert e.code == "DEPENDENCY_ERROR"
        assert e.recoverable is False

    def test_with_dependency_name(self):
        e = DependencyError("missing", dependency="torch")
        assert e.details["dependency"] == "torch"


class TestErrorRecord:
    def test_basic(self):
        exc = ValueError("test")
        r = ErrorRecord(error=exc)
        assert r.error is exc
        assert r.traceback_str != ""
        assert r.context == {}

    def test_with_app_error(self):
        e = AppError("msg", code="E1")
        r = ErrorRecord(error=e)
        d = r.to_dict()
        assert d["type"] == "AppError"
        assert d["code"] == "E1"

    def test_with_regular_exception(self):
        e = RuntimeError("boom")
        r = ErrorRecord(error=e)
        d = r.to_dict()
        assert d["type"] == "RuntimeError"
        assert d["message"] == "boom"

    def test_explicit_traceback(self):
        e = Exception("x")
        r = ErrorRecord(error=e, traceback_str="manual tb")
        assert r.traceback_str == "manual tb"


class TestErrorCollector:
    def test_empty(self):
        c = ErrorCollector()
        assert c.has_errors() is False
        assert c.get_errors() == []
        assert c.get_report() == "No errors recorded."

    def test_add_and_retrieve(self):
        c = ErrorCollector()
        c.add(ValueError("v1"))
        c.add(RuntimeError("r2"))
        assert c.has_errors()
        errors = c.get_errors()
        assert len(errors) == 2
        assert isinstance(errors[0].error, ValueError)
        assert isinstance(errors[1].error, RuntimeError)

    def test_max_errors_eviction(self):
        c = ErrorCollector(max_errors=3)
        c.add(ValueError("1"))
        c.add(ValueError("2"))
        c.add(ValueError("3"))
        c.add(ValueError("4"))
        errors = c.get_errors()
        assert len(errors) == 3
        assert str(errors[0].error) == "2"

    def test_clear(self):
        c = ErrorCollector()
        c.add(ValueError("x"))
        c.clear()
        assert c.has_errors() is False

    def test_add_with_context(self):
        c = ErrorCollector()
        c.add(ValueError("ctx"), context={"key": "val"})
        errors = c.get_errors()
        assert errors[0].context == {"key": "val"}

    def test_get_report_with_errors(self):
        c = ErrorCollector()
        c.add(AppError("test error", code="E999"))
        report = c.get_report()
        assert "Error Report" in report
        assert "E999" in report or "test error" in report

    def test_get_summary(self):
        c = ErrorCollector()
        c.add(ValueError("v"))
        c.add(ValueError("v2"))
        c.add(RuntimeError("r"))
        summary = c.get_summary()
        assert summary["total_errors"] == 3
        assert "ValueError" in summary["error_types"]
        assert "RuntimeError" in summary["error_types"]

    def test_catch_context_manager(self):
        c = ErrorCollector()
        with c.catch(context="test_ctx"):
            raise ValueError("caught")
        assert c.has_errors()
        assert c.get_errors()[0].context == {"context": "test_ctx"}

    def test_catch_no_error(self):
        c = ErrorCollector()
        with c.catch():
            x = 1 + 1
        assert not c.has_errors()

    def test_catch_reraise(self):
        c = ErrorCollector()
        with pytest.raises(ValueError):
            with c.catch(reraise=True):
                raise ValueError("reraised")

    def test_get_errors_returns_copy(self):
        c = ErrorCollector()
        c.add(ValueError("x"))
        errors = c.get_errors()
        errors.clear()
        assert c.has_errors()


class TestErrorHandlerDecorator:
    def test_normal_return(self):
        @error_handler
        def ok() -> str:
            return "hello"
        assert ok() == "hello"

    def test_app_error_passthrough(self):
        @error_handler
        def fail() -> str:
            raise AppError("oops")
        with pytest.raises(AppError):
            fail()

    def test_user_error_passthrough(self):
        @error_handler
        def fail() -> str:
            raise UserError("user oops")
        with pytest.raises(UserError):
            fail()

    def test_regular_error_converts_to_analysis(self):
        @error_handler
        def fail() -> str:
            raise ValueError("bad")
        with pytest.raises(AnalysisError) as exc_info:
            fail()
        assert "bad" in str(exc_info.value)

    def test_preserves_func_name(self):
        @error_handler
        def my_func() -> str:
            return "x"
        assert my_func.__name__ == "my_func"


class TestSafeCall:
    def test_success(self):
        result = safe_call(int, "42")
        assert result == 42

    def test_failure_returns_default(self):
        result = safe_call(int, "not_a_number")
        assert result is None

    def test_custom_default(self):
        result = safe_call(int, "x", default=-1)
        assert result == -1

    def test_with_args_and_kwargs(self):
        result = safe_call(sorted, [3, 1, 2], reverse=True)
        assert result == [3, 2, 1]


class TestErrorContext:
    def test_no_error(self):
        with error_context("test"):
            x = 1
        assert x == 1

    def test_with_exception_reraise(self):
        with pytest.raises(AnalysisError):
            with error_context("ctx1", reraise=True):
                raise ValueError("bad")

    def test_with_app_error_reraise(self):
        with pytest.raises(AppError):
            with error_context("ctx", reraise=True):
                raise AppError("app")

    def test_suppress_app_error(self):
        with error_context("ctx", reraise=False):
            raise AppError("silent")
        # Should not raise