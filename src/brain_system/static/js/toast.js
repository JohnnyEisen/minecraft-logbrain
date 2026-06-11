/* ═══════════════════════════════════════════════
   LogBrain 补丁管理系统 — Toast 通知
   ═══════════════════════════════════════════════ */
'use strict';

const Toast = {
  _container: null,

  _ensure() {
    if (!this._container) {
      this._container = document.createElement('div');
      this._container.className = 'toast-container';
      document.body.appendChild(this._container);
    }
  },

  show(msg, type = 'info', duration = 4000) {
    this._ensure();
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    this._container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateX(20px)';
      el.style.transition = 'all 0.3s ease';
      setTimeout(() => el.remove(), 300);
    }, duration);
  },

  success(msg) { this.show(msg, 'success'); },
  error(msg) { this.show(msg, 'error', 6000); },
  info(msg) { this.show(msg, 'info'); }
};