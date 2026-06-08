# -*- coding: utf-8 -*-
"""补丁管理系统 — 依赖关系管理

功能：
- 依赖图构建 (有向无环图 DAG)
- 拓扑排序 (确定安装顺序)
- 循环依赖检测
- 依赖满足性检查
- 冲突检测与报告
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .models import PatchMeta, ConflictReport


class DependencyGraph:
    """补丁依赖图 — 有向无环图 (DAG)。

    节点: patch_id
    边: A → B 表示 A 依赖 B (B 需先安装)
    """

    def __init__(self):
        self._graph: dict[str, list[str]] = defaultdict(list)  # 邻接表
        self._in_degree: dict[str, int] = defaultdict(int)
        self._nodes: set[str] = set()

    def add_patch(self, meta: PatchMeta):
        """添加补丁节点及其依赖关系。"""
        pid = meta.patch_id
        self._nodes.add(pid)
        if pid not in self._in_degree:
            self._in_degree[pid] = 0

        for dep in meta.dependencies:
            self._graph[dep].append(pid)  # dep → pid (dep 需先于 pid)
            self._in_degree[pid] = self._in_degree.get(pid, 0) + 1
            if dep not in self._nodes:
                self._nodes.add(dep)
                if dep not in self._in_degree:
                    self._in_degree[dep] = self._in_degree.get(dep, 0)

    def build(self, metas: list[PatchMeta]):
        """从补丁列表构建完整依赖图。"""
        self.__init__()
        for meta in metas:
            self.add_patch(meta)

    # --- 拓扑排序 ---

    def topological_sort(self) -> list[str]:
        """拓扑排序返回安装顺序。

        Returns:
            按依赖顺序排列的 patch_id 列表（先安装的在前）。

        Raises:
            ValueError: 如果存在循环依赖。
        """
        in_deg = dict(self._in_degree)
        queue = deque([n for n in self._nodes if in_deg.get(n, 0) == 0])
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in self._graph.get(node, []):
                in_deg[neighbor] -= 1
                if in_deg[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(self._nodes):
            remaining = self._nodes - set(result)
            raise ValueError(f"检测到循环依赖，涉及补丁: {remaining}")

        return result

    # --- 循环依赖检测 ---

    def detect_cycles(self) -> list[list[str]]:
        """检测所有循环依赖。

        Returns:
            循环列表，每个循环是一个 patch_id 列表。
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self._nodes}
        cycles = []

        def dfs(node, path):
            color[node] = GRAY
            path.append(node)
            for neighbor in self._graph.get(node, []):
                if color.get(neighbor, WHITE) == GRAY:
                    # 找到循环
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
                elif color.get(neighbor, WHITE) == WHITE:
                    dfs(neighbor, path)
            path.pop()
            color[node] = BLACK

        for node in self._nodes:
            if color.get(node, WHITE) == WHITE:
                dfs(node, [])

        return cycles

    # --- 依赖满足性 ---

    def check_dependencies_satisfied(
        self, patch_id: str, installed: set[str]
    ) -> tuple[bool, list[str]]:
        """检查指定补丁的依赖是否已满足。

        Args:
            patch_id: 目标补丁
            installed: 已安装的 patch_id 集合

        Returns:
            (all_satisfied, missing_deps)
        """
        # 从图中找到该补丁的依赖
        deps = set()
        for dep, dependents in self._graph.items():
            if patch_id in dependents:
                deps.add(dep)

        missing = [d for d in deps if d not in installed]
        return len(missing) == 0, missing

    def get_install_chain(self, patch_id: str) -> list[str]:
        """获得安装指定补丁所需的完整依赖链（按安装顺序）。"""
        needed = set()

        def collect_deps(pid):
            if pid in needed:
                return
            needed.add(pid)
            for dep, dependents in self._graph.items():
                if pid in dependents and dep in self._nodes:
                    collect_deps(dep)

        collect_deps(patch_id)

        # 只对相关子图做拓扑排序
        sub_in_deg = {n: 0 for n in needed}
        sub_graph = defaultdict(list)
        for dep, dependents in self._graph.items():
            for dep2 in dependents:
                if dep in needed and dep2 in needed:
                    sub_graph[dep].append(dep2)
                    sub_in_deg[dep2] = sub_in_deg.get(dep2, 0) + 1

        queue = deque([n for n in needed if sub_in_deg.get(n, 0) == 0])
        result = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in sub_graph.get(node, []):
                sub_in_deg[neighbor] -= 1
                if sub_in_deg[neighbor] == 0:
                    queue.append(neighbor)

        # 结果包含显式声明依赖关系的补丁，按拓扑顺序排列
        ordered = []
        seen = set()
        for pid in result:
            if pid in self._nodes and pid not in seen:
                ordered.append(pid)
                seen.add(pid)

        return ordered

    @property
    def nodes(self) -> set[str]:
        return set(self._nodes)

    @property
    def edges(self) -> list[tuple[str, str]]:
        result = []
        for src, targets in self._graph.items():
            for tgt in targets:
                result.append((src, tgt))
        return result


# ============================================================
# 冲突检测
# ============================================================

def detect_conflicts(
    metas: list[PatchMeta],
    state: dict[str, Any] | None = None,
) -> ConflictReport:
    """检测补丁之间的冲突。

    检测规则：
    1. 两个补丁修改相同模块 → FILE_OVERLAP
    2. 补丁 A 声明与补丁 B 冲突 → LOGIC_CONFLICT
    3. 补丁要求版本不兼容 → VERSION_CLASH
    4. 依赖不可满足 → DEPENDENCY

    Args:
        metas: 待检查的补丁元数据列表
        state: 当前的 PatchRecord 状态字典（可选）

    Returns:
        ConflictReport 冲突检测报告
    """
    report = ConflictReport()
    conflicts = []

    # 规则 1: 文件重叠检测
    module_owners = defaultdict(list)
    for meta in metas:
        for mod in meta.affected_modules:
            module_owners[mod].append(meta.patch_id)

    for mod, owners in module_owners.items():
        if len(owners) > 1:
            conflicts.append({
                "type": "file_overlap",
                "module": mod,
                "patches": owners,
                "detail": f"补丁 {', '.join(owners)} 修改相同模块: {mod}",
            })

    # 规则 2: 显式冲突声明
    patch_map = {m.patch_id: m for m in metas}
    for meta in metas:
        for conflicted_id in meta.conflicts:
            if conflicted_id in patch_map:
                conflicts.append({
                    "type": "logic_conflict",
                    "patch_a": meta.patch_id,
                    "patch_b": conflicted_id,
                    "detail": (
                        f"补丁 {meta.patch_id} 声明与 "
                        f"{conflicted_id} 冲突"
                    ),
                })

    # 规则 3: 版本冲突
    for meta in metas:
        if meta.replaces:
            replaced = [r for r in meta.replaces if r in patch_map]
            if replaced:
                conflicts.append({
                    "type": "version_clash",
                    "new_patch": meta.patch_id,
                    "replaced": replaced,
                    "detail": (
                        f"补丁 {meta.patch_id} v{meta.version} "
                        f"替代旧版本: {replaced}"
                    ),
                })

    # 规则 4: 依赖不可满足
    all_ids = set(m.patch_id for m in metas)
    for meta in metas:
        missing = [d for d in meta.dependencies if d not in all_ids]
        if missing:
            conflicts.append({
                "type": "dependency",
                "patch": meta.patch_id,
                "missing_deps": missing,
                "detail": (
                    f"补丁 {meta.patch_id} 依赖不可满足: {missing}"
                ),
            })

    report.has_conflicts = len(conflicts) > 0
    report.conflicts = conflicts

    if report.has_conflicts:
        resolutions = []
        for c in conflicts:
            t = c["type"]
            if t == "file_overlap":
                resolutions.append(
                    f"模块 {c['module']} 冲突: 建议合并补丁或指定安装优先级"
                )
            elif t == "logic_conflict":
                resolutions.append(
                    f"{c['patch_a']} vs {c['patch_b']}: 只能安装其中一个"
                )
            elif t == "version_clash":
                resolutions.append(
                    f"{c['replaced']} 将被 {c['new_patch']} 取代"
                )
            elif t == "dependency":
                resolutions.append(
                    f"请先安装依赖: {c['missing_deps']}"
                )
        report.resolution = "; ".join(resolutions)

    return report