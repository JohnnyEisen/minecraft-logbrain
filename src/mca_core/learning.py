from __future__ import annotations
import json
import os
import re
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
import threading
from datetime import datetime

from config.constants import AI_SEMANTIC_LIMIT
from mca_core.scoring import CrashCauseScorer
from mca_core.data_augmentation import augment_crash_log

MAX_PATTERNS = 500
MAX_EMBEDDINGS = 100
MIN_HIT_COUNT = 2
EMBEDDING_MIN_HITS = 3
MAX_PATTERN_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit for pattern JSON files
FEATURE_WEIGHTS = {
    "trait": 3.0,
    "exception": 2.5,
    "stack": 1.5,
    "mod": 2.0,
    "loader": 1.8,
    "java": 1.5,
    "version": 1.2,
    "memory": 1.0,
    "default": 1.0,
}

_RE_EXCEPTIONS = re.compile(r'(?:^|[\s.:])([a-zA-Z0-9_\.$]+(?:Exception|Error))')
_RE_STACK_LINES = re.compile(r'\s+at ([a-zA-Z0-9_\.$]+)\(')
_RE_MOD_ID = re.compile(r"(?:mod\s+id[:\s]+|modid[:\s]+)([a-zA-Z0-9_\-]+)", re.IGNORECASE)
_RE_VERSION = re.compile(r"version[:\s]+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_RE_JAVA_VERSION = re.compile(r"java\s*(?:version|runtime)?[:\s]*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_RE_MEMORY = re.compile(r"(?:allocated|memory|heap)[:\s]*([0-9]+)\s*(?:mb|gb|mib|gib)?", re.IGNORECASE)
_RE_ERROR_CODE = re.compile(r"(?:error|err|exception)[:\s]*([A-Z0-9_]{3,})", re.IGNORECASE)
_RE_THREAD_NAME = re.compile(r"\[(\w+(?:-\d+)?)\]/", re.MULTILINE)
# VULN-011 修复: 添加 {1,10} 上限防止 ReDoS 嵌套量词回溯
_RE_CLASS_NAME = re.compile(r"([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,10})\.[A-Z][a-zA-Z0-9_]*")

_CRITICAL_PATTERNS = [
    (re.compile(r"missing (?:mod|dependency|requirement)"), "missing_dep"),
    (re.compile(r"opengl (?:error|invalid)"), "gl_error"),
    (re.compile(r"glfw error"), "glfw_error"),
    (re.compile(r"mixin apply failed"), "mixin_error"),
    (re.compile(r"incompatible"), "incompatible"),
    (re.compile(r"version conflict"), "ver_conflict"),
    (re.compile(r"failed to load"), "load_fail"),
    (re.compile(r"out of memory|oom|heap space"), "oom_error"),
    (re.compile(r"access violation|segfault|crash"), "native_crash"),
    (re.compile(r"shader(?:s)?\s+(?:compil|load|error)"), "shader_error"),
    (re.compile(r"texture\s+(?:error|missing|failed)"), "texture_error"),
    (re.compile(r"world\s+(?:corrupt|error|failed)"), "world_error"),
    (re.compile(r"saves?\s+(?:corrupt|error|failed)"), "save_error"),
    (re.compile(r"config(?:uration)?\s+(?:error|invalid|missing)"), "config_error"),
    (re.compile(r"json\s+(?:parse|syntax|error)"), "json_error"),
    (re.compile(r"network\s+(?:error|timeout|connection)"), "network_error"),
    (re.compile(r"class\s+not\s+found"), "class_not_found"),
    (re.compile(r"no\s+such\s+method"), "no_such_method"),
    (re.compile(r"illegal\s+(?:argument|state)"), "illegal_state"),
    (re.compile(r"null\s*pointer"), "npe"),
    (re.compile(r"concurrent\s+modification"), "concurrent_mod"),
    (re.compile(r"security\s+(?:exception|violation)"), "security"),
    (re.compile(r"file\s+not\s+found"), "file_not_found"),
    (re.compile(r"permission\s+denied"), "permission_denied"),
]


@dataclass
class Solution:
    text: str
    confidence: float = 0.0


class FeedbackSystem:
    def record(self, pattern_id: str, success: bool) -> None:
        return


class CrashPatternLearner:
    """崩溃模式学习器，支持智能模式匹配和学习。
    
    增强功能：
    - 加权特征提取和相似度计算
    - 增量学习支持
    - 模式持久化
    - 语义引擎接口
    """
    
    def __init__(self, storage_path: str, max_patterns: int = MAX_PATTERNS) -> None:
        self.storage_path = storage_path
        self.max_patterns = max_patterns
        self._patterns: list[dict[str, Any]] = self._load_patterns()
        self._feedback_system = FeedbackSystem()
        self.similarity_threshold = 0.5
        self._lock = threading.RLock()
        self.semantic_encoder = None
        self.semantic_comparator = None
        self._store_embeddings = True
        self._pattern_index: dict[str, int] = {}
        self.scorer = CrashCauseScorer()
        self.cross_encoder_reranker = None  # 由应用初始化组件注入
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """重建模式索引以加速查找。"""
        self._pattern_index.clear()
        for i, p in enumerate(self._patterns):
            key = self._compute_pattern_key(p.get("features", []))
            if key:
                self._pattern_index[key] = i

    def _compute_pattern_key(self, features: list[str]) -> str | None:
        traits = sorted([f for f in features if f.startswith("trait:")])
        exceptions = sorted([f for f in features if f.startswith("exception:")])[:2]
        if traits or exceptions:
            return "|".join(traits + exceptions)
        return None

    @staticmethod
    def _get_feature_set(p: dict[str, Any]) -> set[str]:
        fs = p.get("_feature_set")
        if fs is None:
            fs = set(p.get("features", []))
            p["_feature_set"] = fs
        return fs

    def set_semantic_engine(self, encoder: Any, comparator: Any) -> None:
        self.semantic_encoder = encoder
        self.semantic_comparator = comparator

    def set_cross_encoder(self, reranker: Any) -> None:
        """设置 Cross-Encoder 重排序函数。"""
        self.cross_encoder_reranker = reranker

    def set_store_embeddings(self, enabled: bool) -> None:
        self._store_embeddings = enabled
        if not enabled:
            with self._lock:
                for p in self._patterns:
                    p.pop("embedding", None)
                self._save_patterns()

    def _load_patterns(self) -> list[dict[str, Any]]:
        if os.path.exists(self.storage_path):
            try:
                file_size = os.path.getsize(self.storage_path)
                if file_size > MAX_PATTERN_FILE_SIZE:
                    logging.getLogger(__name__).warning(
                        f"Pattern file too large ({file_size} bytes > {MAX_PATTERN_FILE_SIZE}), skipping load"
                    )
                    return []
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    patterns = json.load(f)
                for p in patterns:
                    p["_feature_set"] = set(p.get("features", []))
                return patterns
            except Exception as e:
                logging.getLogger(__name__).warning(f"Failed to load patterns: {e}")
        return []

    def _save_patterns(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            patterns_to_save = []
            for p in self._patterns:
                clean_pattern = {k: v for k, v in p.items() if not k.startswith('_')}
                patterns_to_save.append(clean_pattern)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(patterns_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to save patterns: {e}")

    def _prune_patterns(self) -> None:
        if len(self._patterns) <= self.max_patterns:
            self._prune_embeddings()
            return
        self._patterns.sort(key=lambda p: p.get("hit_count", 0), reverse=True)
        removed = len(self._patterns) - self.max_patterns
        self._patterns = self._patterns[:self.max_patterns]
        self._rebuild_index()
        self._prune_embeddings()
        if removed > 0:
            logging.getLogger(__name__).debug(f"Pruned {removed} low-activity patterns")

    def _prune_embeddings(self) -> None:
        """清理低价值 embedding，限制内存占用。"""
        embedding_count = sum(1 for p in self._patterns if "embedding" in p)
        if embedding_count <= MAX_EMBEDDINGS:
            return
        
        patterns_with_embedding = [(i, p) for i, p in enumerate(self._patterns) if "embedding" in p]
        patterns_with_embedding.sort(key=lambda x: x[1].get("hit_count", 0), reverse=True)
        
        for i, (idx, p) in enumerate(patterns_with_embedding):
            if i >= MAX_EMBEDDINGS:
                hit_count = p.get("hit_count", 0)
                if hit_count < EMBEDDING_MIN_HITS:
                    p.pop("embedding", None)

    _MAX_EXTRACT_BYTES: int = 512 * 1024

    def _extract_features(self, crash_log: str) -> list[str]:
        if not crash_log:
            return []
        if len(crash_log) > self._MAX_EXTRACT_BYTES:
            crash_log = crash_log[:self._MAX_EXTRACT_BYTES]

        features: set[str] = set()
        lower_log = crash_log.lower()

        exceptions = _RE_EXCEPTIONS.findall(crash_log)
        for exc in exceptions[:10]:
            features.add(f"exception:{exc}")

        stack_lines = _RE_STACK_LINES.findall(crash_log)
        for stack in stack_lines[:15]:
            parts = stack.rsplit('.', 1)
            if len(parts) > 1:
                features.add(f"stack:{parts[0]}")

        for pattern, label in _CRITICAL_PATTERNS:
            if pattern.search(lower_log):
                features.add(f"trait:{label}")

        mod_ids = _RE_MOD_ID.findall(crash_log)
        for mod_id in mod_ids[:5]:
            features.add(f"mod:{mod_id.lower()}")

        versions = _RE_VERSION.findall(crash_log)
        for ver in versions[:3]:
            features.add(f"version:{ver}")

        java_vers = _RE_JAVA_VERSION.findall(crash_log)
        if java_vers:
            features.add(f"java:{java_vers[0]}")

        mem_matches = _RE_MEMORY.findall(crash_log)
        for mem in mem_matches[:2]:
            features.add(f"memory:{mem}")

        if "neoforge" in lower_log:
            features.add("loader:neoforge")
        elif "forge" in lower_log and "fml" in lower_log:
            features.add("loader:forge")
        elif "fabric" in lower_log and "quilt" not in lower_log:
            features.add("loader:fabric")
        elif "quilt" in lower_log:
            features.add("loader:quilt")

        error_codes = _RE_ERROR_CODE.findall(crash_log)
        for code in error_codes[:3]:
            features.add(f"error_code:{code.upper()}")

        thread_names = _RE_THREAD_NAME.findall(crash_log)
        for thread in thread_names[:3]:
            if thread.lower() not in ("main", "thread", "server", "client"):
                features.add(f"thread:{thread.lower()}")

        class_names = _RE_CLASS_NAME.findall(crash_log)
        seen_packages: set[str] = set()
        for cls in class_names[:10]:
            pkg = cls.split('.')[0] if '.' in cls else cls
            if pkg not in seen_packages and pkg not in ("java", "javax", "sun", "com", "org"):
                seen_packages.add(pkg)
                features.add(f"pkg:{pkg}")

        return list(features)

    def _get_feature_weight(self, feature: str) -> float:
        if feature.startswith("trait:"):
            return FEATURE_WEIGHTS["trait"]
        elif feature.startswith("exception:"):
            return FEATURE_WEIGHTS["exception"]
        elif feature.startswith("stack:"):
            return FEATURE_WEIGHTS["stack"]
        elif feature.startswith("mod:"):
            return FEATURE_WEIGHTS["mod"]
        elif feature.startswith("loader:"):
            return FEATURE_WEIGHTS["loader"]
        elif feature.startswith("java:"):
            return FEATURE_WEIGHTS["java"]
        elif feature.startswith("version:"):
            return FEATURE_WEIGHTS["version"]
        elif feature.startswith("memory:"):
            return FEATURE_WEIGHTS["memory"]
        return FEATURE_WEIGHTS["default"]

    def _calculate_weighted_similarity(self, features1: set[str], features2: set[str]) -> float:
        if not features1 or not features2:
            return 0.0

        intersection = features1.intersection(features2)
        
        if not intersection:
            return 0.0

        weighted_intersection = sum(self._get_feature_weight(f) for f in intersection)
        weighted_union = sum(self._get_feature_weight(f) for f in features1.union(features2))
        
        if weighted_union == 0:
            return 0.0

        base_score = weighted_intersection / weighted_union

        trait_matches = sum(1 for f in intersection if f.startswith("trait:"))
        exception_matches = sum(1 for f in intersection if f.startswith("exception:"))

        bonus = 0.0
        if trait_matches > 0:
            bonus += 0.1 * min(trait_matches, 3)
        if exception_matches > 0:
            bonus += 0.05 * min(exception_matches, 2)

        return min(base_score + bonus, 1.0)

    def _calculate_similarity(self, features1: set[str], features2: set[str]) -> float:
        return self._calculate_weighted_similarity(features1, features2)

    def _find_similar_pattern(
        self,
        features: list[str],
        vector: list[float] | None = None
    ) -> tuple[dict[str, Any] | None, float]:
        with self._lock:
            query_features_set = set(features)
            if not query_features_set:
                return None, 0.0

            # 快速精确匹配
            quick_key = self._compute_pattern_key(features)
            if quick_key and quick_key in self._pattern_index:
                idx = self._pattern_index[quick_key]
                p = self._patterns[idx]
                stored_fs = self._get_feature_set(p)
                base_score = self._calculate_similarity(query_features_set, stored_fs)
                if base_score > 0.8:
                    return p, base_score

            # 收集 top-3 候选（用于 Cross-Encoder 重排序）
            top_candidates: list[tuple[dict[str, Any], float]] = []

            for p in self._patterns:
                stored_fs = self._get_feature_set(p)
                base_score = self._calculate_similarity(query_features_set, stored_fs)
                final_score = base_score

                if vector and self.semantic_comparator and "embedding" in p:
                    stored_vector = p["embedding"]
                    sem_score = self.semantic_comparator(vector, stored_vector)
                    final_score = (base_score * 0.4) + (sem_score * 0.6)

                if final_score > 0.01:
                    top_candidates.append((p, final_score))

            if not top_candidates:
                return None, 0.0

            # 按分数排序，保留 top-3
            top_candidates.sort(key=lambda x: x[1], reverse=True)
            top_candidates = top_candidates[:3]

            # Cross-Encoder 重排序：对 top-3 进行精细比较
            if len(top_candidates) > 1 and self.cross_encoder_reranker is not None:
                try:
                    # 从最佳匹配的模式中提取结果文本作为候选
                    query_text = "\n".join(features)
                    candidate_texts = [
                        "\n".join(p.get("result", p.get("features", [])))
                        for p, _ in top_candidates
                    ]
                    reranked = self.cross_encoder_reranker(query_text, candidate_texts, top_k=1)
                    if reranked:
                        best_idx = reranked[0][0]
                        if best_idx < len(top_candidates):
                            return top_candidates[best_idx][0], top_candidates[best_idx][1]
                except Exception:
                    pass

            return top_candidates[0][0], top_candidates[0][1]

    def get_pattern_count(self) -> int:
        with self._lock:
            return len(self._patterns)

    def get_memory_usage(self) -> dict[str, int | float]:
        with self._lock:
            pattern_count = len(self._patterns)
            embedding_count = sum(1 for p in self._patterns if "embedding" in p)
            estimated_embedding_mem = embedding_count * 4 * 1024
            return {
                "pattern_count": pattern_count,
                "embedding_count": embedding_count,
                "estimated_embedding_bytes": estimated_embedding_mem,
                "max_patterns": self.max_patterns
            }

    def learn_from_crash(self, crash_log: str, analysis_result: list[str], _save: bool = True) -> None:
        if not crash_log or not analysis_result:
            return

        features = self._extract_features(crash_log)
        if not features:
            return

        vector = None
        if self.semantic_encoder and self._store_embeddings:
            vector = self.semantic_encoder(crash_log[:AI_SEMANTIC_LIMIT])

        with self._lock:
            match, score = self._find_similar_pattern(features, vector)

            if match and score >= self.similarity_threshold:
                match["result"] = analysis_result
                match["hit_count"] = match.get("hit_count", 0) + 1
                match["last_hit"] = datetime.now().isoformat()
                if vector and self._store_embeddings:
                    match["embedding"] = vector
            else:
                new_pattern: dict[str, Any] = {
                    "features": features,
                    "_feature_set": set(features),
                    "result": analysis_result,
                    "hit_count": 1,
                    "created": datetime.now().isoformat(),
                    "last_hit": datetime.now().isoformat(),
                }
                if vector and self._store_embeddings:
                    new_pattern["embedding"] = vector
                self._patterns.append(new_pattern)
                self._rebuild_index()

            # 数据增强：为新学习到的模式生成变体，提升泛化能力
            if not match or match.get("hit_count", 0) <= 1:
                variants = augment_crash_log(crash_log, num_variants=2)
                for variant in variants:
                    variant_features = self._extract_features(variant)
                    if not variant_features or len(variant_features) < 2:
                        continue
                    variant_key = self._compute_pattern_key(variant_features)
                    if variant_key and variant_key in self._pattern_index:
                        self._patterns[self._pattern_index[variant_key]]["hit_count"] += 1
                        continue
                    variant_pattern: dict[str, Any] = {
                        "features": variant_features,
                        "_feature_set": set(variant_features),
                        "result": analysis_result,
                        "hit_count": 0,
                        "created": datetime.now().isoformat(),
                        "last_hit": datetime.now().isoformat(),
                        "_augmented": True,
                    }
                    if self.semantic_encoder and self._store_embeddings:
                        try:
                            variant_vector = self.semantic_encoder(variant[:AI_SEMANTIC_LIMIT])
                            if variant_vector:
                                variant_pattern["embedding"] = variant_vector
                        except Exception:
                            pass
                    self._patterns.append(variant_pattern)
                if variants:
                    self._rebuild_index()
                    logging.getLogger(__name__).debug(
                        f"数据增强: 从 1 条日志生成了 {len(variants)} 条变体"
                    )

            self._prune_patterns()
            if _save:
                self._save_patterns()

    _RE_DETAIL_FILTER = re.compile(r"(缺失|依赖|需要|前置|->|MOD|mod|冲突|不兼容|conflict|required)", re.IGNORECASE)
    _RE_CRITICAL_FILTER = re.compile(r"(重复|duplicate|opengl|glfw|driver)", re.IGNORECASE)

    def suggest_solutions(self, crash_log: str) -> list[Solution]:
        if not self._patterns:
            return self._scorer_suggestions(crash_log)

        features = self._extract_features(crash_log)

        vector = None
        if self.semantic_encoder and self._store_embeddings:
            vector = self.semantic_encoder(crash_log[:AI_SEMANTIC_LIMIT])

        with self._lock:
            match, score = self._find_similar_pattern(features, vector)

            threshold = self.similarity_threshold
            if vector and self.semantic_comparator:
                threshold = 0.45

            if match and score >= threshold:
                res_list = match.get("result", [])

                if not res_list:
                    return []

                detail_res: list[str] = []
                other_critical: list[str] = []
                
                for line in res_list:
                    stripped = line.strip()
                    if not stripped or "扫描完成" in stripped or "Mod总数" in stripped or "加载器" in stripped:
                        continue
                    if self._RE_DETAIL_FILTER.search(stripped):
                        detail_res.append(stripped)
                    elif self._RE_CRITICAL_FILTER.search(stripped):
                        other_critical.append(stripped)

                final_picks: list[str] = []
                seen: set[str] = set()
                for item in detail_res + other_critical:
                    if item not in seen:
                        final_picks.append(item)
                        seen.add(item)

                if not final_picks:
                    filtered = [l.strip() for l in res_list if l.strip() and "扫描完成" not in l and "Mod总数" not in l and "加载器" not in l]
                    final_picks = filtered[:5]
                else:
                    final_picks = final_picks[:10]

                summary_text = "\n".join(final_picks)
                method = "AI 深度理解" if vector else "关键特征匹配"

                if vector:
                    logging.getLogger(__name__).debug(
                        f"AI Diagnosis Match Score: {score:.4f} (Threshold: {threshold})"
                    )

                return [Solution(
                    text=f"[{method} {score:.0%}] 历史修复建议:\n{summary_text}",
                    confidence=score
                )]

        return self._scorer_suggestions(crash_log)

    def _scorer_suggestions(self, crash_log: str) -> list[Solution]:
        """使用统一评分器提供基础建议（无模式匹配时回退）。"""
        top_causes = self.scorer.get_top_causes(crash_log, top_n=2)
        if not top_causes:
            return []
        cause_text = "\n".join(
            f" - {cause} (置信度: {score:.0%})" for cause, score in top_causes
        )
        return [Solution(
            text=f"[规则匹配] 检测到可能的崩溃原因:\n{cause_text}",
            confidence=max(s for _, s in top_causes)
        )]

    def batch_learn(self, crash_data: list[tuple[str, list[str]]]) -> int:
        learned = 0
        for crash_log, analysis_result in crash_data:
            try:
                self.learn_from_crash(crash_log, analysis_result, _save=False)
                learned += 1
            except Exception as e:
                logging.getLogger(__name__).warning(f"Batch learn failed: {e}")
        if learned > 0:
            with self._lock:
                self._save_patterns()
        return learned

    def export_patterns(self, export_path: str) -> bool:
        """导出模式到指定路径。"""
        try:
            with self._lock:
                with open(export_path, "w", encoding="utf-8") as f:
                    json.dump(self._patterns, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"Export patterns failed: {e}")
            return False

    def import_patterns(self, import_path: str, merge: bool = True) -> int:
        """导入模式，返回导入的数量。"""
        try:
            file_size = os.path.getsize(import_path)
            if file_size > MAX_PATTERN_FILE_SIZE:
                logging.getLogger(__name__).warning(
                    f"Import pattern file too large ({file_size} bytes > {MAX_PATTERN_FILE_SIZE}), skipping"
                )
                return 0
            with open(import_path, "r", encoding="utf-8") as f:
                imported = json.load(f)

            with self._lock:
                if not merge:
                    self._patterns = imported
                else:
                    existing_keys = set()
                    for p in self._patterns:
                        key = self._compute_pattern_key(p.get("features", []))
                        if key:
                            existing_keys.add(key)

                    for p in imported:
                        key = self._compute_pattern_key(p.get("features", []))
                        if key and key not in existing_keys:
                            p["_feature_set"] = set(p.get("features", []))
                            self._patterns.append(p)
                            existing_keys.add(key)

                self._prune_patterns()
                self._rebuild_index()
                self._save_patterns()

            return len(imported)
        except Exception as e:
            logging.getLogger(__name__).error(f"Import patterns failed: {e}")
            return 0

    def get_statistics(self) -> dict[str, Any]:
        """获取学习器统计信息。"""
        with self._lock:
            total_hits = sum(p.get("hit_count", 0) for p in self._patterns)
            avg_hits = total_hits / len(self._patterns) if self._patterns else 0

            trait_counts: Counter = Counter()
            for p in self._patterns:
                for f in p.get("features", []):
                    if f.startswith("trait:"):
                        trait_counts[f[6:]] += 1

            return {
                "total_patterns": len(self._patterns),
                "max_patterns": self.max_patterns,
                "total_hits": total_hits,
                "average_hits": round(avg_hits, 2),
                "top_traits": trait_counts.most_common(10),
                "embedding_enabled": self._store_embeddings,
                "semantic_engine_enabled": self.semantic_encoder is not None,
            }
