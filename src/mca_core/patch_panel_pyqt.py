# -*- coding: utf-8 -*-
"""MCA 补丁管理 — PyQt6 管理面板

提供 PyQt6 原生补丁管理界面，集成到 SiliconeCapsuleApp 中。
该面板使用 PatchSubsystem 作为后端，提供完整的补丁生命周期管理 UI。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Import PatchSubsystem
try:
    from mca_core.patch_manager import PatchSubsystem
except ImportError:
    _src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
    if os.path.exists(_src):
        sys.path.insert(0, _src)
    from mca_core.patch_manager import PatchSubsystem

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))


STATE_COLORS: dict[str, str] = {
    "applied":     "#48bb78",
    "available":   "#4299e1",
    "pending":     "#ecc94b",
    "installing":  "#ed8936",
    "failed":      "#f56565",
    "rolled_back": "#a0aec0",
    "disabled":    "#cbd5e0",
    "superseded":  "#9f7aea",
}

STATE_LABELS: dict[str, str] = {
    "applied":     "已应用",
    "available":   "可用",
    "pending":     "等待中",
    "installing":  "安装中",
    "failed":      "失败",
    "rolled_back": "已回滚",
    "disabled":    "已禁用",
    "superseded":  "已替代",
}


class PatchOperationThread(QThread):
    """后台执行补丁操作，避免阻塞 UI。"""
    finished_signal = pyqtSignal(bool, str)
    progress_signal = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            if isinstance(result, tuple) and len(result) == 2:
                ok, msg = result
            else:
                ok, msg = True, str(result)
            self.finished_signal.emit(ok, msg)
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class PatchPanel(QWidget):
    """补丁管理面板 — 可嵌入 QMainWindow 的独立 Widget。"""

    def __init__(self, patch_dir: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)

        if patch_dir is None:
            patch_dir = os.path.join(ROOT_DIR, "patches")

        self._patch_dir = patch_dir
        self._sub: Optional[PatchSubsystem] = None
        self._thread: Optional[PatchOperationThread] = None
        self._current_patch_id: Optional[str] = None
        self._selected_batch: set[str] = set()

        self._setup_ui()

        QApplication.processEvents()
        self._init_subsystem()

    # ── UI 布局 ───────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._setup_toolbar(layout)
        self._setup_main_area(layout)
        self._setup_statusbar(layout)

    def _setup_toolbar(self, parent_layout):
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self.btn_scan = QPushButton("扫描补丁")
        self.btn_scan.setObjectName("accentButton")
        self.btn_scan.clicked.connect(self._on_scan)

        self.btn_install_all = QPushButton("一键安装全部")
        self.btn_install_all.setObjectName("toolbarBtn")
        self.btn_install_all.clicked.connect(self._on_install_all)

        self.btn_verify_all = QPushButton("校验全部")
        self.btn_verify_all.setObjectName("toolbarBtn")
        self.btn_verify_all.clicked.connect(self._on_verify_all)

        self.btn_upload = QPushButton("上传补丁")
        self.btn_upload.setObjectName("toolbarBtn")
        self.btn_upload.clicked.connect(self._on_upload)

        self.lbl_status = QLabel("初始化中...")
        self.lbl_status.setObjectName("caption")

        bar.addWidget(self.btn_scan)
        bar.addWidget(self.btn_install_all)
        bar.addWidget(self.btn_verify_all)
        bar.addWidget(self.btn_upload)
        bar.addStretch()
        bar.addWidget(self.lbl_status)
        parent_layout.addLayout(bar)

    def _setup_main_area(self, parent_layout):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        self._setup_list_panel(splitter)
        self._setup_detail_panel(splitter)
        splitter.setSizes([420, 320])
        parent_layout.addWidget(splitter, stretch=1)

    def _setup_list_panel(self, splitter):
        panel = QFrame()
        panel.setObjectName("siliconeCard")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        self.chk_select_all = QCheckBox("全选")
        self.chk_select_all.stateChanged.connect(self._on_select_all)

        self.btn_batch_install = QPushButton("批量安装")
        self.btn_batch_install.setObjectName("smallBtn")
        self.btn_batch_install.clicked.connect(self._on_batch_install)
        self.btn_batch_install.setEnabled(False)

        self.btn_batch_rollback = QPushButton("批量回滚")
        self.btn_batch_rollback.setObjectName("smallBtn")
        self.btn_batch_rollback.clicked.connect(self._on_batch_rollback)
        self.btn_batch_rollback.setEnabled(False)

        hdr.addWidget(self.chk_select_all)
        hdr.addWidget(self.btn_batch_install)
        hdr.addWidget(self.btn_batch_rollback)
        hdr.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索补丁...")
        self.search_input.setMaximumWidth(180)
        self.search_input.textChanged.connect(self._on_search)
        hdr.addWidget(self.search_input)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._refresh_list)

        lo.addLayout(hdr)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "补丁ID", "名称", "版本", "状态", "操作"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 80)
        self.table.setColumnWidth(5, 90)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        lo.addWidget(self.table)

        splitter.addWidget(panel)

    def _setup_detail_panel(self, splitter):
        panel = QFrame()
        panel.setObjectName("siliconeCard")
        lo = QVBoxLayout(panel)
        lo.setContentsMargins(6, 6, 6, 6)
        lo.setSpacing(4)

        heading = QLabel("补丁详情")
        heading.setObjectName("sectionHeader")
        lo.addWidget(heading)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        info_tab = QWidget()
        info_lo = QVBoxLayout(info_tab)
        info_lo.setContentsMargins(4, 4, 4, 4)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setPlaceholderText("点击左侧列表中的补丁查看详情...")
        self.detail_text.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 12px; border: none; background: transparent;"
        )
        info_lo.addWidget(self.detail_text)

        actions_tab = QWidget()
        actions_lo = QVBoxLayout(actions_tab)
        actions_lo.setContentsMargins(4, 8, 4, 4)
        actions_lo.setSpacing(6)

        self.btn_install = QPushButton("安装补丁")
        self.btn_install.setObjectName("accentButton")
        self.btn_install.clicked.connect(self._on_install_single)
        self.btn_install.setEnabled(False)

        self.btn_rollback = QPushButton("回滚补丁")
        self.btn_rollback.setObjectName("warningBtn")
        self.btn_rollback.clicked.connect(self._on_rollback_single)
        self.btn_rollback.setEnabled(False)

        self.btn_disable = QPushButton("禁用")
        self.btn_disable.setObjectName("toolbarBtn")
        self.btn_disable.clicked.connect(self._on_disable_single)
        self.btn_disable.setEnabled(False)

        self.btn_enable = QPushButton("启用")
        self.btn_enable.setObjectName("successBtn")
        self.btn_enable.clicked.connect(self._on_enable_single)
        self.btn_enable.setEnabled(False)

        self.btn_verify = QPushButton("校验完整性")
        self.btn_verify.setObjectName("toolbarBtn")
        self.btn_verify.clicked.connect(self._on_verify_single)
        self.btn_verify.setEnabled(False)

        self.chk_cascade = QCheckBox("级联回滚")
        self.chk_cascade.setToolTip("回滚时同时回滚依赖该补丁的所有补丁")

        actions_lo.addWidget(self.btn_install)
        actions_lo.addWidget(self.btn_rollback)
        actions_lo.addWidget(self.chk_cascade)
        actions_lo.addWidget(self.btn_disable)
        actions_lo.addWidget(self.btn_enable)
        actions_lo.addWidget(self.btn_verify)
        actions_lo.addStretch()

        tabs.addTab(info_tab, "详情")
        tabs.addTab(actions_tab, "操作")

        lo.addWidget(tabs)
        splitter.addWidget(panel)

    def _setup_statusbar(self, parent_layout):
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.hide()

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("caption")

        bar.addWidget(self.lbl_summary)
        bar.addStretch()
        bar.addWidget(self.progress)
        parent_layout.addLayout(bar)

    # ── 子系统操作 ─────────────────────────────────────────

    def _init_subsystem(self):
        self._run_async(
            self._do_init,
            on_finish=lambda ok, msg: self._on_init_finished(ok, msg),
        )

    def _do_init(self):
        self._sub = PatchSubsystem(self._patch_dir)
        self._sub.initialize()
        self._sub.startup()
        status = self._sub.status()
        return True, f"已就绪 — {status.total_patches} 个补丁"

    def _on_init_finished(self, ok, msg):
        if ok:
            self.lbl_status.setText(msg)
            self.lbl_status.setObjectName("badgeSuccess")
        else:
            self.lbl_status.setText(f"初始化失败: {msg}")
            self.lbl_status.setObjectName("badgeError")
        self._refresh_list()

    def _set_status(self, text, style):
        self.lbl_status.setText(text)
        self.lbl_status.setObjectName(style)

    def _refresh_list(self):
        if self._sub is None or not self._sub.is_healthy():
            return

        try:
            report = self._sub.generate_report()
            status = self._sub.status()

            self.lbl_summary.setText(
                f"总计: {status.total_patches} | "
                f"已应用: {status.applied} | "
                f"可用: {status.available} | "
                f"失败: {status.failed} | "
                f"已禁用: {status.disabled}"
            )

            patches = sorted(report.patches, key=lambda p: p.get("patch_id", ""))
            search_text = self.search_input.text().lower().strip()

            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(0)

            for p in patches:
                pid = p.get("patch_id", "")
                if search_text and search_text not in pid.lower():
                    match_name = p.get("name", "").lower()
                    if search_text not in match_name:
                        continue

                row = self.table.rowCount()
                self.table.insertRow(row)

                chk = QCheckBox()
                _pid = pid
                _row = row
                chk.stateChanged.connect(lambda s, r=_row, p=_pid: self._on_row_check(r, p, s))
                self.table.setCellWidget(row, 0, chk)

                self.table.setItem(row, 1, QTableWidgetItem(pid))
                self.table.setItem(row, 2, QTableWidgetItem(p.get("name", "")))
                self.table.setItem(row, 3, QTableWidgetItem(p.get("version", "")))

                state = p.get("state", "available")
                label = STATE_LABELS.get(state, state)
                item = QTableWidgetItem(label)
                color = STATE_COLORS.get(state, "#a0aec0")
                item.setForeground(QColor(color))
                self.table.setItem(row, 4, item)

                op_widget = QWidget()
                op_layout = QHBoxLayout(op_widget)
                op_layout.setContentsMargins(2, 0, 2, 0)
                op_layout.setSpacing(2)

                if state in ("available", "rolled_back", "pending"):
                    btn = QPushButton("安装")
                    btn.setObjectName("smallBtn")
                    btn.clicked.connect(lambda _, p=pid: self._on_install_single_pid(p))
                    op_layout.addWidget(btn)

                if state == "applied":
                    btn = QPushButton("回滚")
                    btn.setObjectName("smallBtn")
                    btn.clicked.connect(lambda _, p=pid: self._on_rollback_single_pid(p))
                    op_layout.addWidget(btn)

                if state != "disabled":
                    btn = QPushButton("禁用")
                    btn.setObjectName("smallBtn")
                    btn.clicked.connect(lambda _, p=pid: self._on_disable_single_pid(p))
                    op_layout.addWidget(btn)

                if state == "disabled":
                    btn = QPushButton("启用")
                    btn.setObjectName("smallBtn")
                    btn.clicked.connect(lambda _, p=pid: self._on_enable_single_pid(p))
                    op_layout.addWidget(btn)

                op_layout.addStretch()
                self.table.setCellWidget(row, 5, op_widget)

            self.table.setUpdatesEnabled(True)
        except Exception as e:
            self._set_status(f"刷新失败: {e}", "badgeError")

    # ── 事件处理 ──────────────────────────────────────────

    def _on_scan(self):
        self._set_status("扫描中...", "badgeInfo")
        self._run_async(
            lambda: (self._sub.scan(), self._sub.generate_report(),),
            on_finish=lambda ok, msg: self._on_scan_finished(ok),
        )

    def _on_scan_finished(self, ok):
        if ok:
            self._set_status("扫描完成", "badgeSuccess")
        else:
            self._set_status("扫描失败", "badgeError")
        self._refresh_list()

    def _on_install_all(self):
        reply = QMessageBox.question(
            self, "确认", "确定要安装所有可用补丁吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_status("安装中...", "badgeWarning")
        self._run_async(
            lambda: self._do_install_all(),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _do_install_all(self):
        if self._sub is None:
            return False, "子系统未初始化"
        plan = self._sub.get_install_plan()
        if plan.total_count == 0:
            return True, "没有需要安装的补丁"
        results = []
        for m in plan.patches:
            ok, msg = self._sub.install_patch(m.patch_id)
            results.append((m.patch_id, ok, msg))
        success_count = sum(1 for _, ok, _ in results if ok)
        return True, f"安装完成 — {success_count}/{len(results)} 成功"

    def _on_verify_all(self):
        self._set_status("校验中...", "badgeInfo")
        self._run_async(
            lambda: self._do_verify_all(),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _do_verify_all(self):
        if self._sub is None:
            return False, "子系统未初始化"
        results = self._sub.verify_all()
        failed = [pid for pid, (ok, _) in results.items() if not ok]
        if failed:
            return True, f"校验完成 — {len(failed)} 个补丁校验失败: {', '.join(failed[:5])}..."
        return True, f"校验完成 — 全部 {len(results)} 个补丁通过"

    def _on_upload(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择补丁文件", "", "Python 文件 (*.py)"
        )
        if not file_path:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("补丁元数据")
        dialog.setMinimumWidth(400)
        form = QFormLayout(dialog)

        pid_edit = QLineEdit(os.path.splitext(os.path.basename(file_path))[0])
        name_edit = QLineEdit(os.path.splitext(os.path.basename(file_path))[0])
        ver_edit = QLineEdit("1.0.0")
        desc_edit = QLineEdit("从文件上传")
        form.addRow("补丁 ID:", pid_edit)
        form.addRow("名称:", name_edit)
        form.addRow("版本:", ver_edit)
        form.addRow("描述:", desc_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        from mca_core.patch_manager import PatchMeta
        meta = PatchMeta(
            patch_id=pid_edit.text(),
            name=name_edit.text(),
            version=ver_edit.text(),
            description=desc_edit.text(),
        )

        self._run_async(
            lambda: self._sub.upload_patch(file_path, meta),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _on_install_single(self):
        if self._current_patch_id:
            self._on_install_single_pid(self._current_patch_id)

    def _on_install_single_pid(self, pid):
        reply = QMessageBox.question(
            self, "确认", f"确定要安装补丁 {pid} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_async(
            lambda: self._sub.install_patch(pid),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _on_rollback_single(self):
        if self._current_patch_id:
            self._on_rollback_single_pid(self._current_patch_id)

    def _on_rollback_single_pid(self, pid):
        cascade = self.chk_cascade.isChecked()
        msg_text = f"确定要{'级联' if cascade else ''}回滚补丁 {pid} 吗？"
        reply = QMessageBox.question(
            self, "确认回滚", msg_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_async(
            lambda: self._sub.rollback_patch(pid, cascade=cascade),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _on_disable_single(self):
        if self._current_patch_id:
            self._on_disable_single_pid(self._current_patch_id)

    def _on_disable_single_pid(self, pid):
        self._run_async(
            lambda: self._sub.disable_patch(pid),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _on_enable_single(self):
        if self._current_patch_id:
            self._on_enable_single_pid(self._current_patch_id)

    def _on_enable_single_pid(self, pid):
        self._run_async(
            lambda: self._sub.enable_patch(pid),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _on_verify_single(self):
        if self._current_patch_id:
            pid = self._current_patch_id
            self._run_async(
                lambda: self._sub.verify_integrity(pid),
                on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
            )

    def _on_batch_install(self):
        ids = list(self._selected_batch)
        if not ids:
            return
        reply = QMessageBox.question(
            self, "确认", f"确定要批量安装 {len(ids)} 个补丁吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_async(
            lambda: self._do_batch(lambda pid: self._sub.install_patch(pid), ids),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _on_batch_rollback(self):
        ids = list(self._selected_batch)
        if not ids:
            return
        reply = QMessageBox.question(
            self, "确认", f"确定要批量回滚 {len(ids)} 个补丁吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_async(
            lambda: self._do_batch(lambda pid: self._sub.rollback_patch(pid), ids),
            on_finish=lambda ok, msg: self._on_operation_finished(ok, msg),
        )

    def _do_batch(self, fn, ids):
        results = {}
        for pid in ids:
            results[pid] = fn(pid)
        success = sum(1 for ok, _ in results.values() if ok)
        return True, f"批量操作完成 — {success}/{len(results)} 成功"

    def _on_select_all(self, state):
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(state == Qt.CheckState.Checked.value)

    def _on_row_check(self, row, pid, state):
        if state == Qt.CheckState.Checked.value:
            self._selected_batch.add(pid)
        else:
            self._selected_batch.discard(pid)
        has_selection = len(self._selected_batch) > 0
        self.btn_batch_install.setEnabled(has_selection)
        self.btn_batch_rollback.setEnabled(has_selection)

    def _on_search(self, text):
        self._search_timer.start(300)

    def _on_selection_changed(self):
        items = self.table.selectedItems()
        if not items:
            self._current_patch_id = None
            self._clear_detail_buttons()
            return
        row = items[0].row()
        pid_item = self.table.item(row, 1)
        if pid_item is None:
            return
        self._current_patch_id = pid_item.text()
        self._show_detail(self._current_patch_id)

    def _show_detail(self, pid):
        if self._sub is None:
            return
        try:
            pm = self._sub._pm if hasattr(self._sub, '_pm') else None
            target = None
            if pm is not None and hasattr(pm, 'get_patch'):
                target = pm.get_patch(pid)
            if target is None:
                report = self._sub.generate_report()
                for p in report.patches:
                    if p.get("patch_id") == pid:
                        target = p
                        break
            if target is None:
                self.detail_text.setText(f"未找到补丁: {pid}")
                return

            state = target.get("state", "unknown")
            self.btn_install.setEnabled(state in ("available", "rolled_back", "pending"))
            self.btn_rollback.setEnabled(state == "applied")
            self.btn_disable.setEnabled(state != "disabled")
            self.btn_enable.setEnabled(state == "disabled")
            self.btn_verify.setEnabled(True)

            text = f"""补丁 ID:    {pid}
名称:       {target.get('name', '-')}
版本:       {target.get('version', '-')}
状态:       {STATE_LABELS.get(state, state)}
严重级别:   {target.get('severity', '-')}
作者:       {target.get('author', '-')}
描述:       {target.get('description', '-')}
依赖:       {', '.join(target.get('dependencies', [])) or '无'}
冲突:       {', '.join(target.get('conflicts', [])) or '无'}
影响的模块: {', '.join(target.get('affected_modules', [])) or '无'}
标签:       {', '.join(target.get('tags', [])) or '无'}
"""
            if target.get('installed_at'):
                text += f"安装时间:   {target.get('installed_at', '-')}\n"
            if target.get('error_message'):
                text += f"错误信息:   {target.get('error_message', '')}\n"

            self.detail_text.setText(text)
        except Exception as e:
            self.detail_text.setText(f"加载详情失败: {e}")

    def _clear_detail_buttons(self):
        self.btn_install.setEnabled(False)
        self.btn_rollback.setEnabled(False)
        self.btn_disable.setEnabled(False)
        self.btn_enable.setEnabled(False)
        self.btn_verify.setEnabled(False)
        self.detail_text.clear()

    def _on_operation_finished(self, ok, msg):
        if ok and "失败" not in msg:
            self._set_status(msg, "badgeSuccess")
        else:
            self._set_status(msg, "badgeWarning")
        self._refresh_list()

    def _run_async(self, func, on_finish=None):
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            if not self._thread.wait(2000):
                logging.warning("后台线程未能在2秒内终止，将创建新线程")
            self._thread = None

        if on_finish:

            class _WrappedThread(PatchOperationThread):
                pass

            self._thread = _WrappedThread(func)
            self._thread.finished_signal.connect(
                lambda ok, msg, cb=on_finish: cb(ok, msg)
            )
            self._thread.start()
        else:
            func()

    def closeEvent(self, event):
        if self._sub is not None:
            try:
                self._sub.shutdown()
            except Exception:
                pass
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    panel = PatchPanel()
    panel.setWindowTitle("MCA 补丁管理系统 — PyQt6")
    panel.resize(900, 600)
    panel.show()
    sys.exit(app.exec())