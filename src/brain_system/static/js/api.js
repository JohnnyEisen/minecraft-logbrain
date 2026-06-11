/* ═══════════════════════════════════════════════
   LogBrain 补丁管理系统 — API 调用层
   ═══════════════════════════════════════════════ */
'use strict';

const API = {
  _base: '/api/patches',
  _token: null, // 在 auth 后设置

  setToken(t) { this._token = t; },

  async _fetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (this._token) headers['Authorization'] = 'Bearer ' + this._token;
    const url = this._base + path;
    try {
      const res = await fetch(url, { ...opts, headers });
      if (res.status === 401 || res.status === 403) {
        App.showLogin();
        throw new Error('认证失败');
      }
      return await res.json();
    } catch (e) {
      if (e.message === '认证失败') throw e;
      Toast.error('网络错误: ' + e.message);
      throw e;
    }
  },

  // ── 查询 ──
  async list(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this._fetch('/list' + (qs ? '?' + qs : ''));
  },

  async get(id) {
    return this._fetch('/' + encodeURIComponent(id));
  },

  async depsGraph() {
    return this._fetch('/deps/graph');
  },

  async conflicts() {
    return this._fetch('/conflicts/list');
  },

  async plan() {
    return this._fetch('/plan/preview');
  },

  async report() {
    return this._fetch('/report/full');
  },

  async snapshots() {
    return this._fetch('/snapshots/list');
  },

  // ── 操作 ──
  async scan() {
    return this._fetch('/scan', { method: 'POST' });
  },

  async install(patchId, opts = {}) {
    const qs = new URLSearchParams(opts).toString();
    return this._fetch('/install/' + encodeURIComponent(patchId) + (qs ? '?' + qs : ''), { method: 'POST' });
  },

  async installAll() {
    return this._fetch('/install-all', { method: 'POST' });
  },

  async rollback(patchId, cascade = false) {
    const qs = cascade ? '?cascade=true' : '';
    return this._fetch('/rollback/' + encodeURIComponent(patchId) + qs, { method: 'POST' });
  },

  async disable(patchId) {
    return this._fetch('/disable/' + encodeURIComponent(patchId), { method: 'POST' });
  },

  async enable(patchId) {
    return this._fetch('/enable/' + encodeURIComponent(patchId), { method: 'POST' });
  },

  async verify(patchId) {
    return this._fetch('/verify/' + encodeURIComponent(patchId), { method: 'POST' });
  },

  async verifyAll() {
    return this._fetch('/verify-all', { method: 'POST' });
  },

  async upload(formData) {
    const headers = {};
    if (this._token) headers['Authorization'] = 'Bearer ' + this._token;
    // Do not set Content-Type for FormData (browser sets it with boundary)
    try {
      const res = await fetch(this._base + '/upload', {
        method: 'POST',
        headers,
        body: formData,
      });
      if (res.status === 401 || res.status === 403) {
        App.showLogin();
        throw new Error('认证失败');
      }
      return await res.json();
    } catch (e) {
      if (e.message === '认证失败') throw e;
      Toast.error('上传失败: ' + e.message);
      throw e;
    }
  },

  // 批量操作
  async batchInstall(ids) {
    const results = {};
    for (const id of ids) {
      try { results[id] = await this.install(id); }
      catch { results[id] = { ok: false, message: '请求失败' }; }
    }
    return results;
  },

  async batchRollback(ids) {
    const results = {};
    for (const id of ids) {
      try { results[id] = await this.rollback(id); }
      catch { results[id] = { ok: false, message: '请求失败' }; }
    }
    return results;
  }
};