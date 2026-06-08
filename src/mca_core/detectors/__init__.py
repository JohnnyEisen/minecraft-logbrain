from .base import Detector
from .contracts import AnalysisContext, DetectionResult
from .registry import DetectorRegistry
from .out_of_memory import OutOfMemoryDetector
from .jvm_issues import JvmIssuesDetector
from .version_conflicts import VersionConflictsDetector
from .duplicate_mods import DuplicateModsDetector
from .mod_conflicts import ModConflictsDetector
from .shader_world_conflicts import ShaderWorldConflictsDetector
from .missing_dependencies import MissingDependenciesDetector
from .loader import LoaderDetector
from .missing_geckolib import MissingGeckoLibDetector
from .geckolib_more import GeckoLibMoreDetector
from .gl_errors import GlErrorsDetector
from .startup_crash import StartupCrashDetector
from .world_loading_crash import WorldLoadingCrashDetector
from .entity_update_crash import EntityUpdateCrashDetector
from .optifine_detector import OptiFineDetector
from .cache import DetectorCache, CacheEntry, CacheStats, get_detector_cache
from .performance import (
    PerformanceMonitor,
    DetectorMetrics,
    PerformanceReport,
    get_performance_monitor,
)

__all__ = [
    "Detector",
    "AnalysisContext",
    "DetectionResult",
    "DetectorRegistry",
    "OutOfMemoryDetector",
    "JvmIssuesDetector",
    "VersionConflictsDetector",
    "DuplicateModsDetector",
    "ModConflictsDetector",
    "ShaderWorldConflictsDetector",
    "MissingDependenciesDetector",
    "LoaderDetector",
    "MissingGeckoLibDetector",
    "GeckoLibMoreDetector",
    "GlErrorsDetector",
    "StartupCrashDetector",
    "WorldLoadingCrashDetector",
    "EntityUpdateCrashDetector",
    "OptiFineDetector",
    "DetectorCache",
    "CacheEntry",
    "CacheStats",
    "get_detector_cache",
    "PerformanceMonitor",
    "DetectorMetrics",
    "PerformanceReport",
    "get_performance_monitor",
]
