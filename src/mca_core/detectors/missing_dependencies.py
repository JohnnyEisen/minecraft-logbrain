from __future__ import annotations

import re
from typing import List, Optional, ClassVar

from config.constants import CAUSE_DEP
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class MissingDependenciesDetector(Detector):
    _RE_DETAIL: ClassVar[re.Pattern[str]] = re.compile(
        r"Mod ID:\s*'(?P<mod>[^']+)'\s*,\s*Requested by:\s*'(?P<req>[^']+)'\s*,\s*Expected range:\s*'(?P<range>[^']*)'\s*,\s*Actual version:\s*'(?P<actual>[^']*)'",
        flags=re.IGNORECASE,
    )
    _RE_RANGE: ClassVar[re.Pattern[str]] = re.compile(r"^\s*([\[\(])\s*([^,]*?)\s*,\s*([^\)\]]*?)\s*([\)\]])\s*$")
    _RE_MISSING: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:missing\s+(?:(?:mod|required|mandatory|unsupported|dependency)\s*:?\s*)*"
        r"['\"]?([A-Za-z0-9_.\-]+)['\"]?"
        r"(?:\s+(?:mod|dependency))?|"
        r"requires\s+(?:mod\s+)?['\"\[]?([A-Za-z0-9_.\-]+)(?=[\"'\]@]|\s|$)|"
        r"missing or unsupported mandatory dependencies:?\s*['\"\[]?([A-Za-z0-9_.\-]+)?(?=[\"'\]@]|\s|$)?)",
        flags=re.IGNORECASE,
    )
    # 版本冲突上下文中的 "requires" 不应触发缺失依赖检测
    _RE_VERSION_CONFLICT_CONTEXT: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:version\s+conflict|version\s+mismatch|incompatible\s+mod\s+versions|"
        r"requires\s+\S+@[<>]=|resolution\s+failed)",
        flags=re.IGNORECASE,
    )
    _RE_MOD_ID: ClassVar[re.Pattern[str]] = re.compile(r"Mod ID:\s*'([^']+)'", flags=re.IGNORECASE)
    _RE_CLEAN_INVALID: ClassVar[re.Pattern[str]] = re.compile(r"[^\w\.\-]")
    _RE_CLEAN_LEADING: ClassVar[re.Pattern[str]] = re.compile(r"^[0-9\-_]+")
    _RE_HAS_ALPHA: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z]")
    # 否定句上下文：检测 "no missing", "not missing", "without missing", "all satisfied" 等
    _RE_NEGATIVE_CONTEXT: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:no|not|without|zero|none|never|neither)\s+"
        r"(?:missing|dependency|dependencies|required|mod|library|libraries)",
        re.IGNORECASE,
    )
    _RE_ALL_SATISFIED: ClassVar[re.Pattern[str]] = re.compile(
        r"all\s+(?:dependencies?|mods?|libraries?|requirements?)\s+(?:are\s+)?"
        r"(?:satisfied|present|installed|resolved|ok|fine|met|found|loaded|good|ready)",
        re.IGNORECASE,
    )
    _RE_DEP_CHECK_PASSED: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:dependency|mod)\s+(?:check|validation|scan|verification)\s+"
        r"(?:passed|ok|successful|clean|complete|finished)",
        re.IGNORECASE,
    )
    
    CONFLICT_INDICATORS: ClassVar[tuple[str, ...]] = (
        "is incompatible with",
        "incompatible mod versions",
        "version conflict",
        "version mismatch",
    )
    MISSING_INDICATORS: ClassVar[tuple[str, ...]] = (
        "missing or unsupported mandatory dependencies",
        "missing mod",
        "missing dependency",
        "requires mod",
        "mod id:",
    )
    INVALID_NAMES: ClassVar[frozenset[str]] = frozenset({
        "mods.toml", "sound", "or", "file", "id", "state", "from",
        "dependency", "class", "signature", "jar", "json", "mod",
        "version", "versions", "range",
        # Common English stop-words frequently mis-captured as mod names
        "an", "the", "it", "is", "be", "no", "in", "on", "at", "to",
        "of", "by", "as", "if", "so", "we", "he", "not", "are",
        "was", "has", "had", "can", "all", "but", "for", "this",
        "that", "with", "and", "been", "will", "have", "does",
        "into", "over", "also", "any", "new", "more", "than",
        "one", "two", "use", "get", "set", "may", "just", "only",
        "now", "see", "out", "you", "our", "via", "add", "its",
        "some", "been", "very", "each", "must", "does", "type",
        "name", "line", "note", "long", "main", "path", "data",
        "text", "date", "user", "page", "door", "item", "call",
        "case", "then", "java", "http", "null", "true", "false",
    })

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        txt = crash_log or ""
        found = []

        lower_txt = context.crash_log_lower
        has_conflict_only = any(ind in lower_txt for ind in self.CONFLICT_INDICATORS)
        has_missing_indicator = any(ind in lower_txt for ind in self.MISSING_INDICATORS)
        
        if has_conflict_only and not has_missing_indicator:
            return context.results

        # 否定句预检：如果日志整体是"无缺失依赖"的陈述，跳过
        if self._RE_ALL_SATISFIED.search(txt) or self._RE_DEP_CHECK_PASSED.search(txt):
            if not self._RE_DETAIL.search(txt):
                # 没有实际的 Mod ID 详情，确认是纯否定陈述
                return context.results

        for m in self._RE_DETAIL.finditer(txt):
            mod = m.group("mod").strip()
            req = m.group("req").strip()
            rang = m.group("range").strip()
            actual = m.group("actual").strip()

            comp = self._range_to_comparator(rang)
            if not comp:
                comp = rang or "版本范围未知"

            line = f"{req}（MOD）需要 {mod}（前置）{comp}"
            if actual and actual.upper() != "[MISSING]":
                line += f"，实际版本: {actual}"
            found.append(line)

        if found:
            items_to_add = []
            seen = set()
            for l in found:
                if l not in seen:
                    items_to_add.append("  - " + l)
                    seen.add(l)
            context.add_result_block(
                "检测到可能的缺失依赖（详尽解析）:",
                items_to_add,
                detector=self.get_name(),
                cause_label=CAUSE_DEP
            )
            return context.results

        # 版本冲突上下文中的 "requires" 模式不应触发缺失依赖
        # 例如: "mod_a@1.0 requires mod_c@>=2.0" 是版本冲突，不是缺失依赖
        is_version_conflict = bool(self._RE_VERSION_CONFLICT_CONTEXT.search(txt))

        missing = set()

        for m in self._RE_MISSING.finditer(txt):
            # 检查否定句上下文：匹配前有否定词则跳过
            if self._is_negative_match(txt, m.start()):
                continue

            # 版本冲突上下文中，跳过 "requires" 模式（group 2）
            # 但保留 "missing" 模式（group 1, 3）
            groups_to_check = []
            if m.group(1):
                groups_to_check.append(m.group(1))
            if m.group(2) and not is_version_conflict:
                groups_to_check.append(m.group(2))
            if m.group(3):
                groups_to_check.append(m.group(3))

            for cand_str in groups_to_check:
                cand = self._is_valid_modname(cand_str)
                if cand:
                    missing.add(cand)

        for m in self._RE_MOD_ID.finditer(txt):
            start = max(0, m.start() - 100)
            end = min(len(txt), m.end() + 50)
            context_area = txt[start:end].lower()
            if "missing" in context_area or "required" in context_area or "need" in context_area or "requested by" in context_area:
                # 检查否定句上下文
                if self._RE_NEGATIVE_CONTEXT.search(context_area):
                    continue
                cand = self._is_valid_modname(m.group(1))
                if cand:
                    missing.add(cand)

        if missing:
            items_to_add = [f"  - {mod}" for mod in sorted(missing)]
            context.add_result_block(
                "检测到可能的缺失依赖的MOD:",
                items_to_add,
                detector=self.get_name(),
                cause_label=CAUSE_DEP
            )
        return context.results

    @classmethod
    def _range_to_comparator(cls, rng: str) -> str:
        rng = rng.strip()
        m = cls._RE_RANGE.match(rng)
        if not m:
            return rng or ""
        lb_incl = m.group(1) == "["
        lb = m.group(2).strip()
        ub = m.group(3).strip()
        ub_incl = m.group(4) == "]"
        parts = []
        if lb:
            op = ">=" if lb_incl else ">"
            parts.append(f"{op}{lb}")
        if ub:
            op = "<=" if ub_incl else "<"
            parts.append(f"{op}{ub}")
        return " and ".join(parts)

    @classmethod
    def _is_negative_match(cls, txt: str, match_start: int) -> bool:
        """检查匹配位置前 80 字符内是否有否定词，判断是否为否定句上下文。"""
        ctx_start = max(0, match_start - 80)
        context = txt[ctx_start:match_start].lower()
        # 检查否定前缀 + 关键词
        if cls._RE_NEGATIVE_CONTEXT.search(context):
            return True
        return False

    @classmethod
    def _is_valid_modname(cls, s: str) -> Optional[str]:
        s2 = cls._RE_CLEAN_INVALID.sub("", s or "")
        s2 = cls._RE_CLEAN_LEADING.sub("", s2)
        if not s2 or not cls._RE_HAS_ALPHA.search(s2):
            return None
        low = s2.lower()
        if low in cls.INVALID_NAMES:
            return None
        if len(low) < 3:
            return None
        if s2.isupper() and len(s2) <= 10:
            return None
        return s2

    def get_name(self) -> str:
        return "DependencyDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_DEP
