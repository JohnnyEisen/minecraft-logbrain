/* ═══════════════════════════════════════════════
   MCA 补丁管理系统 — 主应用 (路由 + 导航)
   ═══════════════════════════════════════════════ */
'use strict';

const App = {
  _currentPage: 'dashboard',
  _pages: {},
  _navLinks: {},

  // ── 认证 ──
  init() {
    const appEl = document.getElementById('app');
    const token = sessionStorage.getItem('mca_patch_token');

    if (token) {
      API.setToken(token);
      this._setupAuthedUI();
    } else {
      this.showLogin();
    }
  },

  showLogin() {
    const appEl = document.getElementById('app');
    appEl.className = 'no-auth';
    appEl.innerHTML = `
      <div class="login-card">
        <h1>MCA 补丁管理</h1>
        <p class="subtitle">请输入 API Token 以继续</p>
        <form id="login-form" onsubmit="return false;">
          <input type="password" id="login-token" placeholder="Bearer Token" autofocus>
          <button type="submit" class="btn btn-primary" style="width:100%;">登录</button>
        </form>
        <p style="font-size:11px;color:var(--text-muted);margin-top:12px;">
          Token 存储在会话中，关闭页面后清除
        </p>
      </div>
    `;
    document.getElementById('login-form').onsubmit = () => {
      const t = document.getElementById('login-token').value.trim();
      if (!t) return;
      sessionStorage.setItem('mca_patch_token', t);
      API.setToken(t);
      this._setupAuthedUI();
    };
  },

  _setupAuthedUI() {
    const appEl = document.getElementById('app');
    appEl.className = '';
    appEl.innerHTML = `
      <nav class="sidebar">
        <div class="sidebar-brand">
          <h1>MCA Patch Manager</h1>
          <span>补丁管理系统</span>
        </div>
        <div class="sidebar-nav">
          <a data-page="dashboard" class="active">
            <span class="nav-icon">\u25A3</span><span>仪表盘</span>
          </a>
          <a data-page="list">
            <span class="nav-icon">\u2630</span><span>补丁列表</span>
            <span class="badge" id="nav-total">-</span>
          </a>
          <a data-page="detail" style="display:none;">
            <span class="nav-icon">\u25B8</span><span>补丁详情</span>
          </a>
          <div style="height:1px;background:var(--border-default);margin:8px 12px;"></div>
          <a data-page="snapshots">
            <span class="nav-icon">\u21BA</span><span>回滚快照</span>
          </a>
          <a data-page="conflicts">
            <span class="nav-icon">\u26A0</span><span>冲突检测</span>
          </a>
          <a data-page="depsPage">
            <span class="nav-icon">\u2317</span><span>依赖关系</span>
          </a>
          <div style="height:1px;background:var(--border-default);margin:8px 12px;"></div>
          <a onclick="Modal.uploadForm()" style="cursor:pointer;">
            <span class="nav-icon">\u2B07</span><span>上传补丁</span>
          </a>
        </div>
        <div class="sidebar-footer">
          v2.1.0 | MCA Brain System
        </div>
      </nav>
      <main class="main">
        <div class="page active" data-page="dashboard" id="page-dashboard"></div>
        <div class="page" data-page="list" id="page-list"></div>
        <div class="page" data-page="detail" id="page-detail"></div>
        <div class="page" data-page="snapshots" id="page-snapshots"></div>
        <div class="page" data-page="conflicts" id="page-conflicts"></div>
        <div class="page" data-page="depsPage" id="page-deps-page"></div>
      </main>
    `;

    // 初始化页面
    this._pages = {
      dashboard: document.getElementById('page-dashboard'),
      list: document.getElementById('page-list'),
      detail: document.getElementById('page-detail'),
      snapshots: document.getElementById('page-snapshots'),
      conflicts: document.getElementById('page-conflicts'),
      depsPage: document.getElementById('page-deps-page'),
    };

    // 初始化子模块
    Dashboard.init(this._pages.dashboard);
    ListPage.init(this._pages.list);
    DetailPage.init(this._pages.detail);

    // 导航事件
    document.querySelectorAll('.sidebar-nav a[data-page]').forEach(a => {
      const page = a.dataset.page;
      this._navLinks[page] = a;
      a.addEventListener('click', (e) => {
        e.preventDefault();
        if (window.innerWidth <= 768) {
          // mobile - toggle
        }
        this.navigate(page);
      });
    });

    // 加载仪表盘
    this.navigate('dashboard');
    this._updateCounts();
  },

  // ── 导航 ──
  navigate(page, param) {
    // 激活导航
    document.querySelectorAll('.sidebar-nav a[data-page]').forEach(a => {
      a.classList.remove('active');
    });
    if (this._navLinks[page]) this._navLinks[page].classList.add('active');

    // 切换页面
    Object.values(this._pages).forEach(el => el.classList.remove('active'));
    if (this._pages[page]) this._pages[page].classList.add('active');
    this._currentPage = page;

    // 渲染页面
    switch (page) {
      case 'dashboard': Dashboard.render(); break;
      case 'list': ListPage.render(); break;
      case 'detail': if (param) DetailPage.render(param); break;
      case 'snapshots': this._renderSnapshots(); break;
      case 'conflicts': this._renderConflicts(); break;
      case 'depsPage': this._renderDepsPage(); break;
    }
  },

  // ── 全局操作 ──
  async scan() {
    Toast.info('正在扫描...');
    try {
      const res = await API.scan();
      if (res.ok) { Toast.success(res.message); this.refresh(); }
      else Toast.error(res.message);
    } catch { Toast.error('扫描失败'); }
  },

  async installAll() {
    Modal.confirm('确认安装所有可用补丁?', async () => {
      Toast.info('批量安装中...');
      try {
        const res = await API.installAll();
        if (res.ok) { Toast.success(res.message); this.refresh(); }
        else Toast.error(res.message);
      } catch { Toast.error('安装失败'); }
    });
  },

  async refresh() {
    this._updateCounts();
    if (this._currentPage === 'dashboard') Dashboard.render();
    if (this._currentPage === 'list') ListPage.render();
    if (this._currentPage === 'detail' && DetailPage._patchId) DetailPage.render(DetailPage._patchId);
  },

  async _updateCounts() {
    try {
      const res = await API.list();
      if (res.ok) {
        const badge = document.getElementById('nav-total');
        if (badge) badge.textContent = res.total;
      }
    } catch { /* ignore */ }
  },

  // ── 辅助页面渲染 ──

  async _renderSnapshots() {
    const el = this._pages.snapshots;
    el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">\u23F3 加载中...</div>';
    try {
      const res = await API.snapshots();
      if (!res.ok) { el.innerHTML = '<p>加载失败</p>'; return; }
      const snaps = res.data || [];
      let html = '<div class="topbar"><h2>回滚快照</h2></div><div style="padding:24px 28px;">';
      if (!snaps.length) {
        html += '<div class="empty-state"><div class="empty-icon">\u2205</div><p>没有可用的回滚快照</p></div>';
      } else {
        html += '<div class="detail-section"><h3>可用快照 (' + snaps.length + ')</h3>';
        snaps.forEach(s => {
          html += `<div style="padding:10px 0;border-bottom:1px solid rgba(48,54,61,0.3);">
            <strong style="font-family:var(--font-mono);font-size:13px;">${Utils.escape(s.patch_id)}</strong>
            <span style="color:var(--text-secondary);font-size:12px;margin-left:8px;">v${Utils.escape(s.version)}</span>
            <span style="color:var(--text-muted);font-size:12px;margin-left:8px;">${Utils.fmtDate(s.created_at)}</span>
            <span style="color:var(--text-muted);font-size:12px;margin-left:8px;">${s.backup_count} 个备份</span>
          </div>`;
        });
        html += '</div>';
      }
      html += '</div>';
      el.innerHTML = html;
    } catch { el.innerHTML = '<p>加载失败</p>'; }
  },

  async _renderConflicts() {
    const el = this._pages.conflicts;
    el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">\u23F3 加载中...</div>';
    try {
      const res = await API.conflicts();
      if (!res.ok) { el.innerHTML = '<p>加载失败</p>'; return; }
      const report = res.data || {};
      let html = '<div class="topbar"><h2>冲突检测</h2></div><div style="padding:24px 28px;">';
      if (!report.has_conflicts) {
        html += '<div class="empty-state"><div class="empty-icon">\u2714</div><p>\u2714 未检测到冲突</p></div>';
      } else {
        html += `<p style="margin-bottom:12px;color:var(--accent-orange);">\u26A0 检测到 ${report.conflicts.length} 个冲突</p>`;
        report.conflicts.forEach((c, i) => {
          html += `<div class="detail-section" style="margin-bottom:12px;">
            <h3>冲突 ${i + 1}: ${Utils.escape(c.type)}</h3>
            <p style="font-size:13px;">${Utils.escape(c.detail)}</p>
          </div>`;
        });
        if (report.resolution) {
          html += `<div class="detail-section"><h3>解决建议</h3><p style="font-size:13px;">${Utils.escape(report.resolution)}</p></div>`;
        }
      }
      html += '</div>';
      el.innerHTML = html;
    } catch { el.innerHTML = '<p>加载失败</p>'; }
  },

  async _renderDepsPage() {
    const el = this._pages.depsPage;
    el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">\u23F3 加载中...</div>';
    try {
      const res = await API.depsGraph();
      if (!res.ok) { el.innerHTML = '<p>加载失败</p>'; return; }
      const { nodes, edges } = res.data || { nodes: [], edges: [] };
      let html = '<div class="topbar"><h2>依赖关系图</h2></div><div style="padding:24px 28px;">';
      if (!nodes.length) {
        html += '<div class="empty-state"><div class="empty-icon">\u2205</div><p>没有依赖关系</p></div>';
      } else {
        html += `<p style="color:var(--text-secondary);margin-bottom:16px;font-size:13px;">${nodes.length} 个节点, ${edges.length} 条边</p>`;
        html += '<svg id="full-deps-svg" style="width:100%;height:400px;background:var(--bg-primary);border:1px solid var(--border-default);border-radius:8px;"></svg>';

        // 表格式列表
        html += '<div style="margin-top:20px;"><div class="detail-section"><h3>补丁列表</h3>';
        nodes.forEach(n => {
          html += `<div style="padding:8px 0;border-bottom:1px solid rgba(48,54,61,0.3);display:flex;align-items:center;gap:8px;">`;
          html += `<span style="font-family:var(--font-mono);font-size:12px;color:var(--accent-blue);cursor:pointer;" onclick="App.navigate('detail','${Utils.escape(n)}')">${Utils.escape(n)}</span>`;
          const depsFrom = edges.filter(([f, t]) => f === n).map(([f, t]) => t);
          const depsTo = edges.filter(([f, t]) => t === n).map(([f, t]) => f);
          if (depsFrom.length) html += `<span style="font-size:11px;color:var(--text-muted);">\u2192 ${depsFrom.join(', ')}</span>`;
          if (depsTo.length) html += `<span style="font-size:11px;color:var(--accent-orange);">\u2190 依赖: ${depsTo.join(', ')}</span>`;
          html += '</div>';
        });
        html += '</div></div>';
      }
      html += '</div>';
      el.innerHTML = html;
    } catch { el.innerHTML = '<p>加载失败</p>'; }
  },
};

// ── 启动 ──
document.addEventListener('DOMContentLoaded', () => App.init());