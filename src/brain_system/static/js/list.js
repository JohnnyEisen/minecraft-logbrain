/* ═══════════════════════════════════════════════
   MCA 补丁管理系统 — 补丁列表页
   ═══════════════════════════════════════════════ */
'use strict';

const ListPage = {
  _el: null,
  _data: [],
  _filters: { state: '', sort: 'severity', order: 'desc', search: '' },
  _selected: new Set(),

  init(el) { this._el = el; },

  async render(filters = {}) {
    Object.assign(this._filters, filters);
    this._el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">\u23F3 加载中...</div>';
    try {
      const res = await API.list(this._filters);
      if (!res.ok) { this._el.innerHTML = '<p>加载失败</p>'; return; }
      this._data = res.data || [];
      this._selected.clear();
      this._build(res.summary || {});
    } catch {
      this._el.innerHTML = '<p>加载失败</p>';
    }
  },

  _build(summary) {
    let html = '';

    // 搜索 + 排序
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:12px;flex-wrap:wrap;">';
    html += '<div class="search-box" style="min-width:240px;">';
    html += '<span style="color:var(--text-muted);font-size:14px;">\u2315</span>';
    html += `<input type="text" placeholder="搜索补丁名称/ID/描述..." value="${Utils.escape(this._filters.search)}" id="list-search">`;
    html += '</div>';
    html += '<div style="display:flex;gap:8px;align-items:center;">';
    // 排序
    html += '<select id="list-sort" style="padding:6px 10px;background:var(--bg-input);border:1px solid var(--border-default);border-radius:4px;color:var(--text-primary);font-size:12px;">';
    const sorts = [
      { v: 'severity', l: '严重级别' }, { v: 'date', l: '日期' },
      { v: 'name', l: '名称' }, { v: 'version', l: '版本' },
      { v: 'state', l: '状态' },
    ];
    sorts.forEach(s => html += `<option value="${s.v}" ${s.v === this._filters.sort ? 'selected' : ''}>${s.l}</option>`);
    html += '</select>';
    html += `<button class="btn btn-sm btn-ghost" id="list-order">${this._filters.order === 'asc' ? '\u2191 升序' : '\u2193 降序'}</button>`;
    html += '</div></div>';

    // 筛选标签
    const tabs = [
      { k: '', l: '全部', c: this._data.length },
      { k: 'available', l: '可用', c: summary.available || 0 },
      { k: 'applied', l: '已应用', c: summary.applied || 0 },
      { k: 'pending', l: '等待中', c: summary.pending || 0 },
      { k: 'failed', l: '失败', c: summary.failed || 0 },
      { k: 'rolled_back', l: '已回滚', c: summary.rolled_back || 0 },
      { k: 'disabled', l: '已禁用', c: summary.disabled || 0 },
      { k: 'superseded', l: '已替代', c: summary.superseded || 0 },
    ];
    html += '<div class="filter-tabs">';
    tabs.forEach(t => {
      const active = this._filters.state === t.k ? ' active' : '';
      html += `<button class="filter-tab${active}" data-filter="${t.k}">${t.l} <span class="count">(${t.c})</span></button>`;
    });
    html += '</div>';

    // 批量操作栏
    html += '<div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;min-height:30px;">';
    html += '<span id="batch-count" style="font-size:12px;color:var(--text-muted);display:none;">已选 <strong>0</strong> 项</span>';
    html += '<span style="flex:1;"></span>';
    html += '<button class="btn btn-sm btn-primary" onclick="ListPage._batchInstall()" id="batch-install-btn" style="display:none;">批量安装</button>';
    html += '<button class="btn btn-sm btn-danger" onclick="ListPage._batchRollback()" id="batch-rollback-btn" style="display:none;">批量回滚</button>';
    html += '</div>';

    // 表格
    if (this._data.length === 0) {
      html += '<div class="empty-state"><div class="empty-icon">\u2205</div><p>没有匹配的补丁</p></div>';
    } else {
      html += '<table class="data-table"><thead><tr>';
      html += '<th class="checkbox-cell"><input type="checkbox" id="select-all"></th>';
      html += `<th class="col-id ${this._filters.sort === 'name' ? 'sorted' : ''}" data-sort="name">补丁 ID <span class="sort-arrow">${this._filters.sort === 'name' ? (this._filters.order === 'asc' ? '\u2191' : '\u2193') : '\u2195'}</span></th>`;
      html += `<th class="col-version" data-sort="version">版本</th>`;
      html += `<th class="col-date" data-sort="date">日期</th>`;
      html += `<th class="col-severity" data-sort="severity">级别</th>`;
      html += `<th data-sort="state">状态</th>`;
      html += '<th class="col-tags">标签</th>';
      html += '<th>操作</th>';
      html += '</tr></thead><tbody>';

      this._data.forEach(p => {
        html += `<tr data-patch-id="${Utils.escape(p.patch_id)}" class="${this._selected.has(p.patch_id) ? 'selected' : ''}">`;
        html += `<td class="checkbox-cell"><input type="checkbox" data-select="${Utils.escape(p.patch_id)}" ${this._selected.has(p.patch_id) ? 'checked' : ''}></td>`;
        html += `<td><span class="patch-id" onclick="App.navigate('detail','${Utils.escape(p.patch_id)}')">${Utils.escape(p.patch_id)}</span></td>`;
        html += `<td class="col-version" style="font-family:var(--font-mono);font-size:12px;">${Utils.escape(p.version)}</td>`;
        html += `<td class="col-date" style="font-size:12px;color:var(--text-secondary);">${Utils.fmtShortDate(p.installed_at || p.created_date)}</td>`;
        html += `<td>${Utils.severityBadge(p.severity)}</td>`;
        html += `<td>${Utils.statusBadge(p.state)}</td>`;
        html += `<td class="col-tags">${Utils.tagList(p.tags)}</td>`;
        html += '<td style="white-space:nowrap;">';
        // Context-sensitive action buttons
        if (p.state === 'available' || p.state === 'rolled_back' || p.state === 'pending') {
          html += `<button class="btn btn-sm btn-primary" onclick="ListPage._installOne('${Utils.escape(p.patch_id)}')">安装</button> `;
        }
        if (p.state === 'applied') {
          html += `<button class="btn btn-sm btn-danger" onclick="ListPage._rollbackOne('${Utils.escape(p.patch_id)}')">回滚</button> `;
        }
        html += `<button class="btn btn-sm btn-ghost" onclick="App.navigate('detail','${Utils.escape(p.patch_id)}')">详情</button>`;
        if (p.state !== 'disabled') {
          html += ` <button class="btn btn-sm btn-ghost" onclick="ListPage._disableOne('${Utils.escape(p.patch_id)}')">禁用</button>`;
        } else {
          html += ` <button class="btn btn-sm btn-ghost" onclick="ListPage._enableOne('${Utils.escape(p.patch_id)}')">启用</button>`;
        }
        html += '</td></tr>';
      });
      html += '</tbody></table>';
    }

    this._el.innerHTML = html;
    this._bindEvents();
  },

  _bindEvents() {
    // 搜索
    const searchInput = document.getElementById('list-search');
    if (searchInput) {
      searchInput.oninput = Utils.debounce(() => {
        this._filters.search = searchInput.value;
        this.render();
      }, 300);
    }

    // 排序选择
    const sortSelect = document.getElementById('list-sort');
    if (sortSelect) {
      sortSelect.onchange = () => { this._filters.sort = sortSelect.value; this.render(); };
    }
    const orderBtn = document.getElementById('list-order');
    if (orderBtn) {
      orderBtn.onclick = () => {
        this._filters.order = this._filters.order === 'asc' ? 'desc' : 'asc';
        this.render();
      };
    }

    // 表头排序
    this._el.querySelectorAll('th[data-sort]').forEach(th => {
      th.onclick = () => {
        const newSort = th.dataset.sort;
        if (this._filters.sort === newSort) {
          this._filters.order = this._filters.order === 'asc' ? 'desc' : 'asc';
        } else {
          this._filters.sort = newSort;
          this._filters.order = 'desc';
        }
        this.render();
      };
    });

    // 筛选标签
    this._el.querySelectorAll('.filter-tab').forEach(btn => {
      btn.onclick = () => {
        this._filters.state = btn.dataset.filter;
        this.render();
      };
    });

    // 全选
    const selectAll = document.getElementById('select-all');
    if (selectAll) {
      selectAll.onchange = () => {
        this._el.querySelectorAll('input[data-select]').forEach(cb => {
          cb.checked = selectAll.checked;
          if (selectAll.checked) this._selected.add(cb.dataset.select);
          else this._selected.delete(cb.dataset.select);
        });
        this._updateBatchUI();
      };
    }

    // 单选
    this._el.querySelectorAll('input[data-select]').forEach(cb => {
      cb.onchange = () => {
        if (cb.checked) this._selected.add(cb.dataset.select);
        else this._selected.delete(cb.dataset.select);
        this._updateBatchUI();
      };
    });
  },

  _updateBatchUI() {
    const count = document.getElementById('batch-count');
    const installBtn = document.getElementById('batch-install-btn');
    const rollbackBtn = document.getElementById('batch-rollback-btn');
    const show = this._selected.size > 0;
    if (count) {
      count.style.display = show ? 'inline' : 'none';
      count.innerHTML = '已选 <strong>' + this._selected.size + '</strong> 项';
    }
    if (installBtn) installBtn.style.display = show ? 'inline-flex' : 'none';
    if (rollbackBtn) rollbackBtn.style.display = show ? 'inline-flex' : 'none';
  },

  async _batchInstall() {
    if (this._selected.size === 0) return;
    Modal.confirm(`确认安装 ${this._selected.size} 个补丁?`, async () => {
      Toast.info('批量安装中...');
      const ids = Array.from(this._selected);
      const results = await API.batchInstall(ids);
      const okCount = Object.values(results).filter(r => r.ok).length;
      Toast.success(`完成: ${okCount}/${ids.length} 成功`);
      App.refresh();
      this.render();
    });
  },

  async _batchRollback() {
    if (this._selected.size === 0) return;
    Modal.confirm(`确认回滚 ${this._selected.size} 个补丁? 此操作不可逆。`, async () => {
      Toast.info('批量回滚中...');
      const ids = Array.from(this._selected);
      const results = await API.batchRollback(ids);
      const okCount = Object.values(results).filter(r => r.ok).length;
      Toast.success(`完成: ${okCount}/${ids.length} 成功`);
      App.refresh();
      this.render();
    });
  },

  async _installOne(id) {
    try {
      const res = await API.install(id);
      if (res.ok) {
        Toast.success(res.message);
        App.refresh();
        this.render();
      } else {
        // 依赖不满足
        if (res.message && res.message.includes('依赖不满足')) {
          Modal.confirm(res.message + '\n\n是否带依赖安装?', async () => {
            const res2 = await API.install(id, { with_deps: true });
            if (res2.ok) { Toast.success(res2.message); App.refresh(); this.render(); }
            else Toast.error(res2.message);
          });
        } else {
          Toast.error(res.message);
        }
      }
    } catch { Toast.error('安装失败'); }
  },

  async _rollbackOne(id) {
    Modal.confirm(`确认回滚补丁 ${id}?`, async () => {
      try {
        const res = await API.rollback(id);
        if (res.ok) { Toast.success(res.message); App.refresh(); this.render(); }
        else Toast.error(res.message);
      } catch { Toast.error('回滚失败'); }
    });
  },

  async _disableOne(id) {
    try {
      const res = await API.disable(id);
      if (res.ok) { Toast.success(res.message); App.refresh(); this.render(); }
      else Toast.error(res.message);
    } catch { Toast.error('操作失败'); }
  },

  async _enableOne(id) {
    try {
      const res = await API.enable(id);
      if (res.ok) { Toast.success(res.message); App.refresh(); this.render(); }
      else Toast.error(res.message);
    } catch { Toast.error('操作失败'); }
  },
};