/* ═══════════════════════════════════════════════
   LogBrain 补丁管理系统 — 仪表盘页面
   ═══════════════════════════════════════════════ */
'use strict';

const Dashboard = {
  _el: null,

  init(el) { this._el = el; },

  async render() {
    this._el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">\u23F3 加载中...</div>';
    try {
      const res = await API.report();
      if (!res.ok) { this._el.innerHTML = '<p>加载失败</p>'; return; }
      this._build(res.data);
    } catch {
      this._el.innerHTML = '<p>加载失败</p>';
    }
  },

  _build(report) {
    const cards = [
      { key: 'applied', label: '已应用', icon: '\u2713', cls: 'applied' },
      { key: 'available', label: '可用', icon: '\u25CB', cls: 'available' },
      { key: 'pending', label: '等待中', icon: '\u23F3', cls: 'pending' },
      { key: 'failed', label: '失败', icon: '\u2717', cls: 'failed' },
      { key: 'rolled_back', label: '已回滚', icon: '\u21A9', cls: 'rolled_back' },
      { key: 'disabled', label: '已禁用', icon: '\u29B8', cls: 'disabled' },
      { key: 'superseded', label: '已替代', icon: '\u21C4', cls: 'superseded' },
    ];

    let html = '<div class="stat-grid">';
    cards.forEach(c => {
      const val = report[c.key] || 0;
      html += `
        <div class="stat-card ${c.cls}" onclick="App.navigate('list', {state:'${c.key}'})" title="点击查看 ${c.label} 补丁">
          <div class="stat-value">${val}</div>
          <div class="stat-label">${c.label}</div>
          <div class="stat-icon">${c.icon}</div>
        </div>
      `;
    });
    html += '</div>';

    // 快速操作
    html += '<div style="display:flex;gap:8px;margin-bottom:24px;">';
    html += '<button class="btn btn-primary" onclick="App.installAll()">\u25B6 一键安装全部</button>';
    html += '<button class="btn" onclick="App.scan()">\u21BB 扫描补丁</button>';
    html += '<button class="btn" onclick="App.navigate(\'list\')">\u2630 查看列表</button>';
    html += '<button class="btn btn-ghost" onclick="Modal.uploadForm()">\u2B07 上传补丁</button>';
    html += '</div>';

    // 时间线
    const recents = report.patches
      .filter(p => p.installed_at || p.error)
      .sort((a, b) => (b.installed_at || '').localeCompare(a.installed_at || ''))
      .slice(0, 15);

    if (recents.length) {
      html += '<div class="detail-section"><h3>最近活动</h3><div class="timeline">';
      recents.forEach(p => {
        const cls = p.state === 'applied' ? 'success' : p.state === 'failed' ? 'fail' : '';
        const action = p.state === 'applied' ? '安装' : p.state === 'failed' ? '失败' : p.state === 'rolled_back' ? '回滚' : '操作';
        const time = p.installed_at || p.last_checked_at || '';
        html += `
          <div class="timeline-item ${cls}">
            <strong style="font-family:var(--font-mono);font-size:12px;">${Utils.escape(p.patch_id)}</strong>
            <span style="color:var(--text-secondary);font-size:12px;"> — ${action}</span>
            <div class="time">${Utils.fmtDate(time)}</div>
            ${p.error ? '<div style="color:var(--accent-red);font-size:11px;">' + Utils.escape(p.error) + '</div>' : ''}
          </div>
        `;
      });
      html += '</div></div>';
    }

    this._el.innerHTML = html;
  }
};