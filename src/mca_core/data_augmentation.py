"""
崩溃日志数据增强模块

为学习引擎提供崩溃日志变体生成，提升模型泛化能力。

增强策略：
1. 异常类名变化 - 简写/全限定名互换
2. 内存数值扰动 - 内存大小 ±20% 随机变化
3. 行顺序打乱 - 无关行的顺序不影响语义
4. 噪声注入 - 模拟日志中的额外调试信息
"""

from __future__ import annotations

import random
import re
from typing import List, Optional


class CrashLogAugmenter:
    """崩溃日志数据增强器。

    从一条真实崩溃日志生成多条语义等价但文本不同的变体，
    用于丰富学习引擎的训练数据。

    使用方式:
        augmenter = CrashLogAugmenter()
        variants = augmenter.augment(crash_log, num_variants=3)
    """

    # 异常类名映射：简写 ↔ 全限定名
    _EXCEPTION_ALIASES = {
        "OutOfMemoryError": "java.lang.OutOfMemoryError",
        "ClassNotFoundException": "java.lang.ClassNotFoundException",
        "NoClassDefFoundError": "java.lang.NoClassDefFoundError",
        "NoSuchMethodError": "java.lang.NoSuchMethodError",
        "NullPointerException": "java.lang.NullPointerException",
        "IllegalArgumentException": "java.lang.IllegalArgumentException",
        "IllegalStateException": "java.lang.IllegalStateException",
        "RuntimeException": "java.lang.RuntimeException",
        "ArrayIndexOutOfBoundsException": "java.lang.ArrayIndexOutOfBoundsException",
        "FileNotFoundException": "java.io.FileNotFoundException",
        "IOException": "java.io.IOException",
        "SocketException": "java.net.SocketException",
        "GLFWError": "GLFW error",
        "OpenGLError": "OpenGL error",
    }

    # 噪声行模板
    _NOISE_TEMPLATES = [
        "[Server thread/INFO]: Autosave started",
        "[Server thread/INFO]: Autosave complete",
        "[Render thread/DEBUG]: Chunk rebuild queued",
        "[Netty Client IO/DEBUG]: Received packet",
        "[Worker-Main/INFO]: Preparing spawn area: {:.0f}%",
    ]

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)

    def augment(self, crash_log: str, num_variants: int = 3) -> List[str]:
        """生成崩溃日志变体。

        Args:
            crash_log: 原始崩溃日志
            num_variants: 生成变体数量

        Returns:
            变体日志列表（不含原始日志）
        """
        if not crash_log or num_variants <= 0:
            return []

        lines = crash_log.split("\n")
        variants: List[str] = []

        strategies = [
            self._swap_exception_names,
            self._perturb_memory_values,
            self._shuffle_noise_lines,
            self._inject_noise,
            self._truncate_stack_trace,
        ]

        for _ in range(num_variants):
            strategy = self._rng.choice(strategies)
            try:
                variant = strategy(lines)
                if variant and variant != crash_log:
                    variants.append(variant)
            except Exception:
                continue

        return variants

    def _swap_exception_names(self, lines: List[str]) -> str:
        """随机替换异常类名（简写 ↔ 全限定名）。"""
        result = list(lines)
        swaps = list(self._EXCEPTION_ALIASES.items())
        self._rng.shuffle(swaps)

        swapped = 0
        for short_name, full_name in swaps:
            if swapped >= 2:
                break
            for i, line in enumerate(result):
                # 全限定名 → 简写（全限定名在前，避免短名匹配到全限定名的子串）
                if full_name in line:
                    result[i] = line.replace(full_name, short_name)
                    swapped += 1
                    break
                # 简写 → 全限定名（仅当不包含全限定名时才替换）
                elif short_name in line and full_name not in line:
                    result[i] = line.replace(short_name, full_name)
                    swapped += 1
                    break

        return "\n".join(result)

    def _perturb_memory_values(self, lines: List[str]) -> str:
        """随机扰动内存数值（±20%）。"""
        result = list(lines)
        mem_pattern = re.compile(r"(\d+)(MB|GB|mb|gb|MiB|GiB)")

        for i, line in enumerate(result):
            def _replace(match):
                val = int(match.group(1))
                factor = self._rng.uniform(0.8, 1.2)
                new_val = max(1, int(val * factor))
                return f"{new_val}{match.group(2)}"
            result[i] = mem_pattern.sub(_replace, line)

        return "\n".join(result)

    def _shuffle_noise_lines(self, lines: List[str]) -> str:
        """打乱非关键行的顺序。"""
        # 找到异常行，保持其位置不变
        exception_idx = None
        for i, line in enumerate(lines):
            if any(kw in line for kw in ["Error", "Exception", "Caused by", "FATAL"]):
                exception_idx = i
                break

        if exception_idx is None or len(lines) < 5:
            return "\n".join(lines)

        # 异常行之前和之后的行分别打乱
        before = lines[:exception_idx]
        after = lines[exception_idx + 1:]

        self._rng.shuffle(before)
        self._rng.shuffle(after)

        return "\n".join(before + [lines[exception_idx]] + after)

    def _inject_noise(self, lines: List[str]) -> str:
        """注入无关噪声行。"""
        result = list(lines)
        num_noise = self._rng.randint(1, 3)
        positions = sorted(self._rng.sample(range(len(result) + 1), num_noise))

        for offset, pos in enumerate(positions):
            template = self._rng.choice(self._NOISE_TEMPLATES)
            noise = template.format(self._rng.uniform(10, 99))
            result.insert(pos + offset, noise)

        return "\n".join(result)

    def _truncate_stack_trace(self, lines: List[str]) -> str:
        """随机截断堆栈跟踪（保留关键行）。"""
        # 找到 "at " 开头的行，随机删除一部分
        result = []
        at_indices = [i for i, line in enumerate(lines) if line.strip().startswith("at ")]

        if len(at_indices) <= 3:
            return "\n".join(lines)

        keep_count = max(1, len(at_indices) - self._rng.randint(1, min(5, len(at_indices) - 1)))
        keep_indices = set(self._rng.sample(at_indices, keep_count))

        for i, line in enumerate(lines):
            if i in at_indices and i not in keep_indices:
                if self._rng.random() < 0.3:
                    result.append("\t... {} more".format(len(at_indices) - keep_count))
                    continue
            result.append(line)

        return "\n".join(result)


# 便捷函数
def augment_crash_log(crash_log: str, num_variants: int = 3) -> List[str]:
    """对崩溃日志进行数据增强，生成语义等价的变体。"""
    augmenter = CrashLogAugmenter()
    return augmenter.augment(crash_log, num_variants)