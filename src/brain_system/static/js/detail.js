/* ═══════════════════════════════════════════════
   MCA 补丁管理系统 — 补丁详情页
   ═══════════════════════════════════════════════ */
'use strict';

const DetailPage = {
  _el: null,
  _patchId: null,
  _data: null,

  init(el) { this._el = el; },

  async render(patchId) {
    this._patchId = patchId;
    this._el.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted);">\u23F3 加载中...</div>';
    try {
      const res = await API.get(patchId);
      if (!res.ok) { this._el.innerHTML = '<p>补丁不存在</p>'; return; }
      this._data = res.data;
      this._build();
      this._loadDepsGraph();
    } catch {
      this._el.innerHTML = '<p>加载失败</p>';
    }
  },

  _build() {
    const d = this._data;
    let html = '';

    // 标题栏
    html += '<div class="topbar">';
    html += `<h2>${Utils.escape(d.patch_id)} <span style="font-size:13px;color:var(--text-secondary);font-weight:400;">v${Utils.escape(d.version)}</span></h2>`;
    html += '<div class="topbar-actions">';
    html += '<button class="btn btn-ghost" onclick="App.navigate(\'list\')">\u2190 返回列表</button>';

    if (d.state === 'available' || d.state === 'rolled_back' || d.state === 'pending') {
      html += '<button class="btn btn-primary" id="detail-install">\u25B6 安装</button>';
    }
    if (d.state === 'applied') {
      html += '<button class="btn btn-danger" id="detail-rollback">\u21A9 回滚</button>';
    }
    if (d.state !== 'disabled') {
      html += `<button class="btn btn-ghost" id="detail-disable">${'\u29B8'} 禁用</button>`;
    } else {
      html += '<button class="btn btn-ghost" id="detail-enable">\u25C9 启用</button>';
    }
    html += '</div></div>';

    html += '<div style="padding:24px 28px;">';

    // 元数据网格
    html += '<div class="detail-grid">';
    html += '<div class="detail-section"><h3>基本信息</h3>';
    const fields = [
      ['名称', d.name], ['版本', d.version], ['描述', d.description],
      ['作者', d.author], ['创建日期', Utils.fmtDate(d.created_date)],
      ['严重级别', Utils.severityBadge(d.severity)],
      ['目标版本', d.target_version],
    ];
    fields.forEach(f => {
      html += '<div class="detail-field">';
      html += `<span class="field-label">${f[0]}</span>`;
      html += `<span class="field-value">${f[1] || '-'}</span>`;
      html += '</div>';
    });
    html += '</div>';

    html += '<div class="detail-section"><h3>运行时状态</h3>';
    const stateFields = [
      ['状态', Utils.statusBadge(d.state || 'available')],
      ['安装版本', d.installed_version || '-'],
      ['安装时间', Utils.fmtDate(d.installed_at)],
      ['安装序号', d.install_order || '-'],
    ];
    stateFields.forEach(f => {
      html += '<div class="detail-field">';
      html += `<span class="field-label">${f[0]}</span>`;
      html += `<span class="field-value">${f[1]}</span>`;
      html += '</div>';
    });
    if (d.error_message) {
      html += `<div class="detail-field"><span class="field-label">错误</span><span class="field-value" style="color:var(--accent-red);">${Utils.escape(d.error_message)}</span></div>`;
    }
    html += '</div>';

    // 依赖
    html += '<div class="detail-section"><h3>依赖关系</h3>';
    if (d.dependencies && d.dependencies.length) {
      html += '<div><ul style="padding-left:20px;font-size:13px;">';
      d.dependencies.forEach(dep => {
        html += `<li style="margin-bottom:4px;"><a href="#" onclick="App.navigate('detail','${Utils.escape(dep)}');return false;" style="color:var(--accent-blue);font-family:var(--font-mono);">${Utils.escape(dep)}</a></li>`;
      });
      html += '</ul></div>';
    } else {
      html += '<p style="color:var(--text-muted);font-size:13px;">无依赖</p>';
    }
    html += '</div>';

    // 冲突
    html += '<div class="detail-section"><h3>冲突</h3>';
    if (d.conflicts && d.conflicts.length) {
      html += '<div><ul style="padding-left:20px;font-size:13px;">';
      d.conflicts.forEach(c => {
        html += `<li style="color:var(--accent-red);margin-bottom:4px;font-family:var(--font-mono);">${Utils.escape(c)}</li>`;
      });
      html += '</ul></div>';
    } else {
      html += '<p style="color:var(--text-muted);font-size:13px;">无冲突</p>';
    }
    html += '</div>';

    // 标签 + 文件哈希
    html += '<div class="detail-section"><h3>标签</h3>';
    html += Utils.tagList(d.tags) || '<p style="color:var(--text-muted);font-size:13px;">无标签</p>';
    html += '</div>';

    html += '<div class="detail-section"><h3>文件信息</h3>';
    html += '<div class="detail-field"><span class="field-label">文件哈希</span><span class="field-value" style="font-size:10px;">' + (d.file_hash ? d.file_hash : '-') + '</span></div>';
    html += '<div class="detail-field"><span class="field-label">签名</span><span class="field-value" style="font-size:10px;">' + (d.signature ? d.signature.substring(0, 32) + '...' : '-') + '</span></div>';
    html += '<div class="detail-field"><span class="field-label">回滚点</span><span class="field-value" style="font-size:10px;">' + (d.rollback_point_id || '-') + '</span></div>';
    html += '</div>';

    // 替代关系
    if (d.replaces && d.replaces.length) {
      html += '<div class="detail-section"><h3>替代的补丁</h3><ul style="padding-left:20px;font-size:13px;">';
      d.replaces.forEach(r => html += `<li style="font-family:var(--font-mono);">${Utils.escape(r)}</li>`);
      html += '</ul></div>';
    }

    // 影响模块
    if (d.affected_modules && d.affected_modules.length) {
      html += '<div class="detail-section"><h3>影响模块</h3>';
      html += '<div class="tag-list">' + d.affected_modules.map(m => `<span class="tag">${Utils.escape(m)}</span>`).join('') + '</div>';
      html += '</div>';
    }

    html += '</div>'; // end detail-grid

    // 依赖关系图
    html += '<div class="detail-section full" style="margin-top:20px;"><h3>依赖关系图</h3>';
    html += '<svg class="deps-svg" id="deps-graph"></svg></div>';

    // 操作按钮区
    html += '<div class="detail-actions">';
    html += '<button class="btn" onclick="App.navigate(\'list\');">\u25C0 返回列表</button>';
    html += '<button class="btn btn-ghost" id="detail-verify">\u2714 校验完整性</button>';
    html += '</div>';

    html += '</div>'; // end padding

    this._el.innerHTML = html;
    this._bindActions();
  },

  _bindActions() {
    const d = this._data || {};

    const installBtn = document.getElementById('detail-install');
    if (installBtn) {
      installBtn.onclick = () => {
        API.install(d.patch_id).then(res => {
          if (res.ok) { Toast.success(res.message); this.render(d.patch_id); }
          else if (res.message && res.message.includes('依赖不满足')) {
            Modal.confirm(res.message + '\n\n是否带依赖安装?', async () => {
              const res2 = await API.install(d.patch_id, { with_deps: true });
              if (res2.ok) { Toast.success(res2.message); this.render(d.patch_id); }
              else Toast.error(res2.message);
            });
          }
          else Toast.error(res.message);
        });
      };
    }

    const rollbackBtn = document.getElementById('detail-rollback');
    if (rollbackBtn) {
      rollbackBtn.onclick = () => {
        Modal.confirm(`确认回滚 ${d.patch_id} v${d.version}?`, () => {
          API.rollback(d.patch_id).then(res => {
            if (res.ok) { Toast.success(res.message); this.render(d.patch_id); }
            else Toast.error(res.message);
          });
        });
      };
    }

    const disableBtn = document.getElementById('detail-disable');
    if (disableBtn) {
      disableBtn.onclick = () => {
        API.disable(d.patch_id).then(res => {
          if (res.ok) { Toast.success(res.message); this.render(d.patch_id); }
          else Toast.error(res.message);
        });
      };
    }

    const enableBtn = document.getElementById('detail-enable');
    if (enableBtn) {
      enableBtn.onclick = () => {
        API.enable(d.patch_id).then(res => {
          if (res.ok) { Toast.success(res.message); this.render(d.patch_id); }
          else Toast.error(res.message);
        });
      };
    }

    const verifyBtn = document.getElementById('detail-verify');
    if (verifyBtn) {
      verifyBtn.onclick = () => {
        API.verify(d.patch_id).then(res => {
          if (res.ok && res.data && res.data.passed) Toast.success('\u2714 完整性校验通过');
          else Toast.error(res.message || '校验失败');
        });
      };
    }
  },

  async _loadDepsGraph() {
    try {
      const res = await API.depsGraph();
      if (!res.ok || !res.data) return;
      const { nodes, edges } = res.data;
      const svg = document.getElementById('deps-graph');
      if (!svg || !nodes.length) {
        if (svg) svg.parentElement.innerHTML += '<p style="color:var(--text-muted);font-size:12px;text-align:center;margin-top:8px;">无依赖关系</p>';
        return;
      }

      // 简单的力导向布局
      const w = svg.clientWidth || 600;
      const h = 300;
      const positions = {};
      const centerX = w / 2;
      const centerY = h / 2;

      // 放置节点（圆形布局）
      const radius = Math.min(w, h) * 0.35;
      const currentNode = this._patchId;
      const deps = [];
      const dependents = [];

      edges.forEach(([from, to]) => {
        if (to === currentNode) deps.push(from);
        if (from === currentNode) dependents.push(to);
      });

      const allDisplayed = [currentNode, ...deps, ...dependents].filter((v, i, a) => a.indexOf(v) === i);

      allDisplayed.forEach((n, i) => {
        const angle = (i / Math.max(allDisplayed.length, 1)) * 2 * Math.PI - Math.PI / 2;
        positions[n] = {
          x: centerX + Math.cos(angle) * radius,
          y: centerY + Math.sin(angle) * radius * 0.6,
          isTarget: n === currentNode,
          isDep: deps.includes(n),
          isDependent: dependents.includes(n),
        };
      });

      // 绘制 SVG
      svg.setAttribute('viewBox', `0 0 ${w} ${h}`);

      let svgContent = '';

      // 边
      edges.forEach(([from, to]) => {
        const p1 = positions[from];
        const p2 = positions[to];
        if (p1 && p2) {
          const color = to === currentNode ? 'var(--accent-orange)' :
                        from === currentNode ? 'var(--accent-blue)' : 'var(--border-default)';
          svgContent += `<line x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}" stroke="${color}" stroke-width="1.5" stroke-dasharray="${to === currentNode ? '' : '4,3'}" opacity="0.6"/>`;
        }
      });

      // 节点
      allDisplayed.forEach((n) => {
        const p = positions[n];
        let fill = 'var(--accent-blue)';
        let rx = 6;
        if (p.isTarget) { fill = 'var(--accent-green)'; rx = 8; }
        else if (p.isDep) fill = 'var(--accent-orange)';
        else if (p.isDependent) fill = 'var(--accent-purple)';

        svgContent += `<rect x="${p.x - 70}" y="${p.y - 14}" width="140" height="28" rx="${rx}" fill="${fill}" fill-opacity="0.15" stroke="${fill}" stroke-opacity="0.6" stroke-width="1"/>`;
        svgContent += `<text x="${p.x}" y="${p.y + 4}" text-anchor="middle" fill="${fill}" font-family="JetBrains Mono, monospace" font-size="11px">${Utils.escape(n)}</text>`;
      });

      // 图例
      svgContent += '<text x="10" y="' + (h - 10) + '" fill="var(--text-muted)" font-family="IBM Plex Sans, sans-serif" font-size="10">\u25CF 当前补丁 \u25CF 依赖 \u25CF 被依赖</text>';

      svg.innerHTML = svgContent;
    } catch {
      // 静默失败
    }
  }
};