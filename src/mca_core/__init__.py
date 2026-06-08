from __future__ import annotations

__all__ = [
    "DiagnosticEngine",
    "AnalysisState",
    "load_gpu_rules",
    "EventBus",
    "get_event_bus",
    "reset_event_bus",
    "ThreadPoolManager",
    "submit_task",
    "TimeoutError",
    "with_timeout",
    "run_with_timeout",
    "AppError",
    "AnalysisError",
    "ThreadSafeState",
    "DIContainer",
    "AuditTrail",
]

_LAZY_IMPORTS = {
    "DiagnosticEngine": ("mca_core.diagnostic_engine", "DiagnosticEngine"),
    "AnalysisState": ("mca_core.analysis_engine", "AnalysisState"),
    "load_gpu_rules": ("mca_core.analysis_engine", "load_gpu_rules"),
    "EventBus": ("mca_core.events", "EventBus"),
    "get_event_bus": ("mca_core.events", "get_event_bus"),
    "reset_event_bus": ("mca_core.events", "reset_event_bus"),
    "ThreadPoolManager": ("mca_core.threading_utils", "ThreadPoolManager"),
    "submit_task": ("mca_core.threading_utils", "submit_task"),
    "TimeoutError": ("mca_core.threading_utils", "TimeoutError"),
    "with_timeout": ("mca_core.threading_utils", "with_timeout"),
    "run_with_timeout": ("mca_core.threading_utils", "run_with_timeout"),
    "AppError": ("mca_core.errors", "AppError"),
    "AnalysisError": ("mca_core.errors", "AnalysisError"),
    "ThreadSafeState": ("mca_core.state", "ThreadSafeState"),
    "DIContainer": ("mca_core.di", "DIContainer"),
    "AuditTrail": ("mca_core.audit", "AuditTrail"),
}

import importlib as _importlib


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_name, attr_name = _LAZY_IMPORTS[name]
        module = _importlib.import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")