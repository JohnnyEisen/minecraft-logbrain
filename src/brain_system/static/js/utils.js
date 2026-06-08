/* ═══════════════════════════════════════════════
   MCA 补丁管理系统 — 工具函数
   ═══════════════════════════════════════════════ */
'use strict';

const Utils = {
  // HTML 实体转义
  escape(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  },

  // 格式化 ISO 日期
  fmtDate(iso) {
    if (!iso) return '-';
    try { return new Date(iso).toLocaleString('zh-CN'); } catch { return iso; }
  },

  // 格式化简短的日期
  fmtShortDate(iso) {
    if (!iso) return '-';
    try {
      const d = new Date(iso);
      return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    } catch { return iso; }
  },

  // 状态中文名
  stateLabel(s) {
    const map = {
      applied: '已应用', available: '可用', pending: '等待中',
      installing: '安装中', failed: '失败', rolled_back: '已回滚',
      disabled: '已禁用', superseded: '已替代'
    };
    return map[s] || s;
  },

  // 严重级别中文名
  severityLabel(s) {
    const map = { critical: '严重', high: '高', medium: '中', low: '低', optional: '可选' };
    return map[s] || s;
  },

  // 状态图标 (SVG 单字符)
  stateIcon(s) {
    const map = {
      applied: '\u2713', available: '\u25CB', pending: '\u23F3',
      failed: '\u2717', rolled_back: '\u21A9', installing: '\u2699',
      disabled: '\u29B8', superseded: '\u21C4'
    };
    return map[s] || '\u25CB';
  },

  // 防抖
  debounce(fn, ms = 300) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  },

  // 动画数字
  animateNumber(el, from, to, duration = 600) {
    const start = performance.now();
    const step = (ts) => {
      const p = Math.min((ts - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(from + (to - from) * eased);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  },

  // 渲染状态徽标 HTML
  statusBadge(state) {
    const label = this.stateLabel(state);
    return `<span class="status-badge ${state}">${label}</span>`;
  },

  // 渲染严重级别 HTML
  severityBadge(severity) {
    const label = this.severityLabel(severity);
    return `<span class="severity-badge severity-${severity}">${label}</span>`;
  },

  // 渲染标签列表
  tagList(tags) {
    if (!tags || !tags.length) return '';
    return '<div class="tag-list">' + tags.map(t => `<span class="tag">${this.escape(t)}</span>`).join('') + '</div>';
  },

  // 生成 UUID (简化)
  uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }
};