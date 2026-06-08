from __future__ import annotations

import re
from collections import Counter, OrderedDict
from typing import ClassVar, List, Optional

from config.constants import CAUSE_DUP
from .base import Detector
from .contracts import AnalysisContext, DetectionResult


class DuplicateModsDetector(Detector):
    IGNORE_PREFIXES = frozenset({
        "fmlcore", "client", "authlib", "fmlloader", "modlauncher",
        "bootstraplauncher", "forge", "minecraft", "netty", "libraries",
        "javafmllanguage", "securejarhandler", "lowcodelanguage", "mclanguage",
        "java", "jdk", "lwjgl", "jopt", "gson", "guava", "commons",
        "log4j", "slf4j", "jline", "jna", "oshi", "mixin", "spongepowered",
        "mixinbooter",
    })

    _JAR_PATTERN = re.compile(
        r"([A-Za-z][A-Za-z0-9_.\-]*-[0-9][A-Za-z0-9_.\-]+)\.jar", re.IGNORECASE
    )

    _TEXT_DUP_PATTERN = re.compile(
        r"(?:found duplicate mod|duplicate mods? found|multiple files for mod|"
        r"duplicate mod detected|found in both|副本|重复.*mod)",
        re.IGNORECASE,
    )

    _IGNORE_KEYWORD_PATTERN = re.compile(
        r"(?:loader|launcher|bootstrap|authlib|client|fml|forge|library|libraries|core)",
        re.IGNORECASE,
    )

    _mod_patterns: ClassVar[OrderedDict[str, re.Pattern[str]]] = OrderedDict()
    _MOD_PATTERNS_MAX = 100

    @classmethod
    def _get_mod_pattern(cls, modid: str) -> re.Pattern[str]:
        if modid in cls._mod_patterns:
            cls._mod_patterns.move_to_end(modid)
            return cls._mod_patterns[modid]

        if len(cls._mod_patterns) >= cls._MOD_PATTERNS_MAX:
            cls._mod_patterns.popitem(last=False)

        pattern = re.compile(
            rf"{re.escape(modid)}-[0-9][A-Za-z0-9\.\-_]+\.jar",
            re.IGNORECASE,
        )
        cls._mod_patterns[modid] = pattern
        return pattern

    @staticmethod
    def _should_ignore_jar(base: str, lowjar: str) -> bool:
        if base in DuplicateModsDetector.IGNORE_PREFIXES:
            return True
        return bool(DuplicateModsDetector._IGNORE_KEYWORD_PATTERN.search(lowjar))

    def detect(self, crash_log: str, context: AnalysisContext) -> List[DetectionResult]:
        analyzer = context.analyzer

        jar_matches = self._JAR_PATTERN.findall(crash_log)
        jar_counts = Counter(jar_matches)

        mod_jar_counts: Counter = Counter()
        for jar, count in jar_counts.items():
            lowjar = jar.lower()
            base = lowjar.split("-", 1)[0]
            if self._should_ignore_jar(base, lowjar):
                continue
            mod_jar_counts[base] += count

        duplicates = []
        for jar, count in jar_counts.items():
            lowjar = jar.lower()
            base = lowjar.split("-", 1)[0]
            if self._should_ignore_jar(base, lowjar):
                continue
            if count >= 20:
                duplicates.append(f"{jar}.jar appears {count} times")

        text_dup_match = self._TEXT_DUP_PATTERN.search(crash_log)
        if text_dup_match and not duplicates:
            # 提取有意义的重复模组名称
            dup_context = crash_log[text_dup_match.start():text_dup_match.start() + 500]
            mod_names = self._JAR_PATTERN.findall(dup_context)
            if mod_names:
                duplicates.append(f"检测到重复Mod: {', '.join(mod_names[:5])}")
            elif "duplicate mod" in dup_context.lower():
                duplicates.append("检测到重复Mod（文本匹配）")

        if hasattr(analyzer, "mods") and analyzer.mods:
            for modid, vers in analyzer.mods.items():
                if not modid:
                    continue
                low = modid.lower()
                if not re.search(r"[a-z]", low):
                    continue
                if any(low.startswith(p) for p in self.IGNORE_PREFIXES):
                    continue

                occurrences = mod_jar_counts.get(low, 0)
                if occurrences == 0:
                    pattern = self._get_mod_pattern(modid)
                    occurrences = len(pattern.findall(crash_log))

                if occurrences >= 20:
                    desc = f"{modid}*.jar appears {occurrences} times"
                    if desc not in duplicates:
                        duplicates.append(desc)

        if duplicates:
            unique_dups = list(dict.fromkeys(duplicates))
            MAX_DISPLAY = 5

            items_to_add = []
            if len(unique_dups) > MAX_DISPLAY:
                items_to_add.extend("  - " + d for d in unique_dups[:MAX_DISPLAY])
                items_to_add.append(
                    f"  ... (and {len(unique_dups) - MAX_DISPLAY} more)"
                )
            else:
                items_to_add.extend("  - " + d for d in unique_dups)

            context.add_result_block(
                "日志中存在大量重复 JAR 引用（可能来自文件扫描器，非运行时冲突）:",
                items_to_add,
                detector=self.get_name(),
                cause_label=CAUSE_DUP,
                confidence=0.7,
            )

        return context.results

    def get_name(self) -> str:
        return "DuplicateModsDetector"

    def get_cause_label(self) -> Optional[str]:
        return CAUSE_DUP