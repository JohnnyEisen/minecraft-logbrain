/* ═══════════════════════════════════════════════
   LogBrain 补丁管理系统 — UI 组件库
   Modal, Confirm, Steps, Timeline
   ═══════════════════════════════════════════════ */
'use strict';

const Modal = {
  _overlay: null,
  _container: null,

  _ensure() {
    if (!this._overlay) {
      this._overlay = document.createElement('div');
      this._overlay.className = 'modal-overlay';
      this._overlay.onclick = (e) => { if (e.target === this._overlay) this.close(); };
      document.body.appendChild(this._overlay);
    }
  },

  open(content, title = '') {
    this._ensure();
    this._overlay.innerHTML = `
      <div class="modal">
        ${title ? '<h3>' + Utils.escape(title) + '</h3>' : ''}
        <div class="modal-body">${content}</div>
      </div>
    `;
    this._overlay.classList.add('open');
  },

  close() {
    if (this._overlay) this._overlay.classList.remove('open');
  },

  // 确认对话框
  confirm(msg, onOk, onCancel) {
    const id = Utils.uuid();
    const content = `
      <p>${Utils.escape(msg)}</p>
      <div class="modal-actions">
        <button class="btn btn-ghost" data-modal-cancel="${id}">取消</button>
        <button class="btn btn-primary" data-modal-ok="${id}">确认</button>
      </div>
    `;
    this.open(content, '确认操作');
    setTimeout(() => {
      const okBtn = document.querySelector('[data-modal-ok="' + id + '"]');
      const cancelBtn = document.querySelector('[data-modal-cancel="' + id + '"]');
      if (okBtn) okBtn.onclick = () => { this.close(); if (onOk) onOk(); };
      if (cancelBtn) cancelBtn.onclick = () => { this.close(); if (onCancel) onCancel(); };
    }, 50);
  },

  // 上传表单
  uploadForm(onSubmit) {
    const content = `
      <div class="upload-zone" id="upload-zone">
        <div class="upload-icon">\u2B07</div>
        <p>拖拽 .py 补丁文件到此处，或点击选择</p>
        <input type="file" accept=".py" hidden id="upload-file-input">
      </div>
      <div id="upload-file-info" style="display:none; margin-top:12px; padding:8px; background:var(--bg-overlay); border-radius:4px; font-family:var(--font-mono); font-size:12px;"></div>
      <div style="margin-top:16px;">
        <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">补丁 ID</label>
        <input type="text" id="upload-patch-id" style="width:100%;padding:6px 10px;background:var(--bg-input);border:1px solid var(--border-default);border-radius:4px;color:var(--text-primary);font-size:13px;font-family:var(--font-mono);" placeholder="例如: hotfix_new_feature">
      </div>
      <div style="margin-top:12px;">
        <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">版本</label>
        <input type="text" id="upload-version" value="1.0.0" style="width:100%;padding:6px 10px;background:var(--bg-input);border:1px solid var(--border-default);border-radius:4px;color:var(--text-primary);font-size:13px;font-family:var(--font-mono);">
      </div>
      <div style="margin-top:12px;">
        <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">描述</label>
        <input type="text" id="upload-desc" style="width:100%;padding:6px 10px;background:var(--bg-input);border:1px solid var(--border-default);border-radius:4px;color:var(--text-primary);font-size:13px;" placeholder="简要描述补丁功能">
      </div>
      <div style="margin-top:12px;">
        <label style="font-size:12px;color:var(--text-secondary);display:block;margin-bottom:4px;">严重级别</label>
        <select id="upload-severity" style="width:100%;padding:6px 10px;background:var(--bg-input);border:1px solid var(--border-default);border-radius:4px;color:var(--text-primary);font-size:13px;">
          <option value="medium">中</option>
          <option value="critical">严重</option>
          <option value="high">高</option>
          <option value="low">低</option>
          <option value="optional">可选</option>
        </select>
      </div>
      <div class="modal-actions" style="margin-top:16px;">
        <button class="btn btn-ghost" onclick="Modal.close()">取消</button>
        <button class="btn btn-primary" id="upload-submit-btn">上传</button>
      </div>
    `;
    this.open(content, '上传补丁');

    // 延迟绑定事件
    setTimeout(() => {
      const zone = document.getElementById('upload-zone');
      const input = document.getElementById('upload-file-input');
      const info = document.getElementById('upload-file-info');
      const idInput = document.getElementById('upload-patch-id');
      let selectedFile = null;

      if (zone && input) {
        zone.onclick = () => input.click();
        zone.ondragover = (e) => { e.preventDefault(); zone.classList.add('dragover'); };
        zone.ondragleave = () => zone.classList.remove('dragover');
        zone.ondrop = (e) => {
          e.preventDefault();
          zone.classList.remove('dragover');
          if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
        };
        input.onchange = () => { if (input.files.length) handleFile(input.files[0]); };
      }

      function handleFile(file) {
        if (!file.name.endsWith('.py')) {
          Toast.error('仅支持 .py 文件');
          return;
        }
        selectedFile = file;
        info.style.display = 'block';
        info.textContent = '\u2714 ' + file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
        if (!idInput.value) {
          idInput.value = file.name.replace('.py', '');
        }
      }

      const submitBtn = document.getElementById('upload-submit-btn');
      if (submitBtn) {
        submitBtn.onclick = async () => {
          if (!selectedFile) { Toast.error('请先选择文件'); return; }
          const patchId = idInput.value.trim();
          if (!patchId) { Toast.error('请输入补丁 ID'); return; }

          const formData = new FormData();
          formData.append('file', selectedFile);
          formData.append('meta_json', JSON.stringify({
            patch_id: patchId,
            name: patchId,
            version: document.getElementById('upload-version').value || '1.0.0',
            description: document.getElementById('upload-desc').value || '',
            severity: document.getElementById('upload-severity').value,
          }));

          try {
            const res = await API.upload(formData);
            if (res.ok) {
              Toast.success(res.message);
              Modal.close();
              App.refresh();
            } else {
              Toast.error(res.message);
            }
          } catch (e) {
            Toast.error('上传失败');
          }
        };
      }
    }, 100);
  }
};