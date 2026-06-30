if (!document.body.classList.contains('kindle-redirect-checked')) {
  document.body.classList.add('kindle-redirect-checked');
  if (new URLSearchParams(location.search).get('kindle') === '1') {
    window.location.replace('/cheap');
  }
}

// ---------------------------------------------------------------------------
// Auth state — drives which tabs are unlocked and which header buttons show.
// ---------------------------------------------------------------------------

let authenticated = false;

const tabsEl = document.querySelectorAll('.tabs button');
const panels = document.querySelectorAll('.tab');
const btnDeploy = document.getElementById('btn-deploy');
const btnLogout = document.getElementById('btn-logout');
const authBadge = document.getElementById('auth-badge');

function applyAuthState(isAuthed) {
  authenticated = !!isAuthed;
  document.querySelectorAll('.tabs button[data-auth]').forEach((b) => {
    b.classList.toggle('locked', !authenticated);
  });
  btnDeploy.hidden = authenticated;
  btnLogout.hidden = !authenticated;
  authBadge.hidden = !authenticated;
  // If the currently active tab requires auth and we just logged out, jump
  // back to the public monitor tab.
  if (!authenticated) {
    const active = document.querySelector('.tabs button.active');
    if (active && active.hasAttribute('data-auth')) selectTab('monitor');
  }
  loadCommandButtons();
}

function selectTab(name) {
  tabsEl.forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  panels.forEach((p) => p.classList.toggle('visible', p.id === `tab-${name}`));
  if (name === 'terminal') initTerminal();
  if (name === 'monitor') initMonitor();
}

tabsEl.forEach((btn) => {
  btn.addEventListener('click', () => {
    if (btn.hasAttribute('data-auth') && !authenticated) {
      openLoginModal();
      return;
    }
    selectTab(btn.dataset.tab);
  });
});

// Init: ask the server whether we already have a valid session cookie.
fetch('/api/auth-status')
  .then((r) => r.json())
  .then((j) => applyAuthState(j.authenticated))
  .catch(() => applyAuthState(false));

// ---------------------------------------------------------------------------
// Deploy / login modal
// ---------------------------------------------------------------------------

const modal = document.getElementById('login-modal');
const loginForm = document.getElementById('login-form');
const loginPwd = document.getElementById('login-password');
const loginErr = document.getElementById('login-err');

function openLoginModal() {
  modal.hidden = false;
  loginErr.textContent = '';
  loginPwd.value = '';
  setTimeout(() => loginPwd.focus(), 30);
}
function closeLoginModal() { modal.hidden = true; }

btnDeploy.addEventListener('click', openLoginModal);
document.getElementById('login-cancel').addEventListener('click', closeLoginModal);
modal.addEventListener('click', (ev) => { if (ev.target === modal) closeLoginModal(); });
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && !modal.hidden) closeLoginModal();
});

loginForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  loginErr.textContent = '';
  const fd = new FormData();
  fd.set('password', loginPwd.value);
  try {
    const resp = await fetch('/login', { method: 'POST', body: fd });
    if (resp.ok) {
      applyAuthState(true);
      closeLoginModal();
      selectTab('commands');
    } else {
      loginErr.textContent = '密码错误';
    }
  } catch (e) {
    loginErr.textContent = '请求失败：' + e;
  }
});

btnLogout.addEventListener('click', async () => {
  await fetch('/logout', { method: 'POST' });
  applyAuthState(false);
});

// ---------------------------------------------------------------------------
// Status pills — driven by /api/status/stream (public)
// ---------------------------------------------------------------------------

function applyStatus(s) {
  document.getElementById('pill-host').textContent = `host=${s.host ?? '?'}`;
  document.getElementById('pill-ip').textContent = `ip=${s.ip ?? '?'}`;
  document.getElementById('pill-cpu').textContent =
    `cpu=${s.cpu_pct != null ? s.cpu_pct.toFixed(1) + '%' : '?'}`;
  document.getElementById('pill-mem').textContent =
    `mem=${s.mem_pct != null ? s.mem_pct.toFixed(1) + '%' : '?'}`;
  document.getElementById('pill-temp').textContent =
    `temp=${s.temp_c != null ? s.temp_c.toFixed(1) + 'C' : '?'}`;
  document.getElementById('pill-up').textContent = `up=${s.uptime ?? '?'}`;
}

(function startStatusSse() {
  let backoff = 1000;
  function connect() {
    const es = new EventSource('/api/status/stream');
    es.onmessage = (ev) => {
      try { applyStatus(JSON.parse(ev.data)); backoff = 1000; }
      catch (e) { /* ignore */ }
    };
    es.onerror = () => {
      es.close();
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
  }
  fetch('/api/status').then((r) => r.ok && r.json().then(applyStatus));
  connect();
})();

// ---------------------------------------------------------------------------
// Commands tab — requires auth
// ---------------------------------------------------------------------------

const cmdForm = document.getElementById('cmd-form');
const cmdInput = document.getElementById('cmd-input');
const cmdOutput = document.getElementById('cmd-output');

function appendOutput(prefix, text) {
  const ts = new Date().toLocaleTimeString();
  cmdOutput.textContent += `[${ts}] ${prefix} ${text}\n`;
  cmdOutput.scrollTop = cmdOutput.scrollHeight;
}

async function runCommand(command) {
  appendOutput('$', command);
  try {
    const resp = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    });
    if (resp.status === 401) {
      appendOutput('!', '会话已过期，请重新点击 Deploy 登录');
      applyAuthState(false);
      openLoginModal();
      return;
    }
    const body = await resp.json();
    appendOutput(' ', body.result ?? JSON.stringify(body));
  } catch (e) {
    appendOutput('!', `ERR ${e}`);
  }
}

cmdForm.addEventListener('submit', (ev) => {
  ev.preventDefault();
  const cmd = cmdInput.value.trim();
  if (!cmd) return;
  cmdInput.value = '';
  runCommand(cmd);
});

// ---------------------------------------------------------------------------
// Commands: instances, templates, recent (persisted on server)
// ---------------------------------------------------------------------------

const instancesRoot = document.getElementById('cmd-instances');
const templatesRoot = document.getElementById('cmd-templates');
const recentRoot = document.getElementById('cmd-recent');
let commandButtons = [];
let commandRecent = [];
let editingButtonId = null;
let pointerDrag = null;

function clearDragOverMarkers() {
  document.querySelectorAll('.btn-manage-row.drag-over').forEach((el) => el.classList.remove('drag-over'));
}

function manageRowAtPoint(x, y, ignoreRow) {
  if (ignoreRow) ignoreRow.style.pointerEvents = 'none';
  const el = document.elementFromPoint(x, y);
  if (ignoreRow) ignoreRow.style.pointerEvents = '';
  return el?.closest('.btn-manage-row') || null;
}

function attachDragHandle(handle, row, btn, kind) {
  handle.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    pointerDrag = { sourceId: btn.id, kind, row, pointerId: ev.pointerId, handle };
    row.classList.add('dragging');
    handle.setPointerCapture(ev.pointerId);
  });

  handle.addEventListener('pointermove', (ev) => {
    if (!pointerDrag || pointerDrag.pointerId !== ev.pointerId) return;
    clearDragOverMarkers();
    const target = manageRowAtPoint(ev.clientX, ev.clientY, pointerDrag.row);
    if (target && target.dataset.kind === pointerDrag.kind && target.dataset.id !== pointerDrag.sourceId) {
      target.classList.add('drag-over');
    }
  });

  const finishDrag = async (ev) => {
    if (!pointerDrag || pointerDrag.pointerId !== ev.pointerId) return;
    const { sourceId, kind, row: srcRow, handle: h } = pointerDrag;
    const target = manageRowAtPoint(ev.clientX, ev.clientY, srcRow);
    clearDragOverMarkers();
    srcRow.classList.remove('dragging');
    pointerDrag = null;
    try { h.releasePointerCapture(ev.pointerId); } catch (_) { /* already released */ }
    if (target && target.dataset.kind === kind) {
      const targetId = target.dataset.id;
      if (targetId && targetId !== sourceId) {
        await reorderByDrag(sourceId, targetId, kind);
      }
    }
  };

  handle.addEventListener('pointerup', finishDrag);
  handle.addEventListener('pointercancel', finishDrag);
}

function newButtonId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `btn-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function isTemplate(btn) {
  return btn.type === 'template';
}

function splitButtons() {
  const instances = commandButtons.filter((b) => !isTemplate(b));
  const templates = commandButtons.filter((b) => isTemplate(b));
  return { instances, templates };
}

function mergeButtons(instances, templates) {
  commandButtons = [...instances, ...templates];
}

function applyCommandParams(command, paramValues) {
  let out = command;
  Object.entries(paramValues).forEach(([name, value]) => {
    out = out.split(`\${${name}}`).join(value);
  });
  return out;
}

function renderButtonGroup(root, buttons, emptyText) {
  root.innerHTML = '';
  if (!buttons.length) {
    root.innerHTML = `<p class="muted">${emptyText}</p>`;
    return;
  }
  buttons.forEach((btn) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.textContent = btn.label;
    if (btn.danger) el.classList.add('danger');
    if (isTemplate(btn) && btn.params?.length) {
      el.title = `参数：${btn.params.map((p) => p.name).join(', ')}`;
    }
    el.addEventListener('click', () => runQuickButton(btn));
    root.appendChild(el);
  });
}

function renderRecentList() {
  recentRoot.innerHTML = '';
  if (!commandRecent.length) {
    recentRoot.innerHTML = '<p class="muted">暂无记录，执行模板命令后会出现在这里。</p>';
    return;
  }
  commandRecent.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'recent-row';
    const from = item.template_label
      ? `<span class="muted recent-from">来自模板：${escapeHtml(item.template_label)}</span>`
      : '';
    row.innerHTML = `
      <div class="recent-info">
        <code class="cmd-preview" title="${escapeHtml(item.command)}">${escapeHtml(item.command)}</code>
        ${from}
      </div>
      <div class="recent-actions">
        <button type="button" class="ghost btn-sm" data-action="run">执行</button>
        <button type="button" class="ghost btn-sm" data-action="save">存为命令</button>
      </div>`;
    row.querySelector('[data-action="run"]').addEventListener('click', () => {
      if (!authenticated) { openLoginModal(); return; }
      runCommand(item.command);
    });
    row.querySelector('[data-action="save"]').addEventListener('click', () => promoteRecent(item));
    recentRoot.appendChild(row);
  });
}

function renderCommandUi() {
  const { instances, templates } = splitButtons();
  renderButtonGroup(instancesRoot, instances, '暂无命令，点击「管理」添加。');
  renderButtonGroup(templatesRoot, templates, '暂无模板，点击「管理」添加。');
  renderRecentList();
}

function runQuickButton(btn) {
  if (!authenticated) { openLoginModal(); return; }
  if (isTemplate(btn)) {
    openRunModal(btn);
    return;
  }
  if (btn.danger && !window.confirm(`确认执行 ${btn.command}？`)) return;
  runCommand(btn.command);
}

async function loadCommandButtons() {
  if (!authenticated) {
    commandButtons = [];
    commandRecent = [];
    renderCommandUi();
    return;
  }
  try {
    const resp = await fetch('/api/command-buttons');
    if (resp.status === 401) {
      applyAuthState(false);
      return;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json();
    commandButtons = Array.isArray(body.buttons) ? body.buttons : [];
    commandRecent = Array.isArray(body.recent) ? body.recent : [];
    renderCommandUi();
  } catch (e) {
    instancesRoot.innerHTML = `<p class="err">加载失败：${escapeHtml(e)}</p>`;
    templatesRoot.innerHTML = '';
    recentRoot.innerHTML = '';
  }
}

async function persistCommandButtons() {
  const resp = await fetch('/api/command-buttons', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ buttons: commandButtons }),
  });
  if (resp.status === 401) {
    applyAuthState(false);
    openLoginModal();
    throw new Error('未登录');
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${resp.status}`);
  }
  const body = await resp.json();
  commandButtons = body.buttons || commandButtons;
  commandRecent = body.recent || commandRecent;
  renderCommandUi();
}

async function recordRecent(command, template) {
  const resp = await fetch('/api/command-buttons/recent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command,
      template_id: template?.id || null,
      template_label: template?.label || null,
    }),
  });
  if (!resp.ok) return;
  const body = await resp.json();
  commandRecent = body.recent || commandRecent;
  renderRecentList();
}

async function promoteRecent(item) {
  if (!authenticated) { openLoginModal(); return; }
  const label = window.prompt('命令名称', item.template_label || item.command.slice(0, 40));
  if (label === null) return;
  try {
    const resp = await fetch('/api/command-buttons/promote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recent_id: item.id, label: label.trim() || undefined }),
    });
    if (resp.status === 401) {
      applyAuthState(false);
      openLoginModal();
      return;
    }
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${resp.status}`);
    }
    const body = await resp.json();
    commandButtons = body.buttons || commandButtons;
    commandRecent = body.recent || commandRecent;
    renderCommandUi();
  } catch (e) {
    window.alert(String(e.message || e));
  }
}

const btnManageModal = document.getElementById('btn-manage-modal');
const btnManageInstances = document.getElementById('btn-manage-instances');
const btnManageTemplates = document.getElementById('btn-manage-templates');
const btnManageErr = document.getElementById('btn-manage-err');
const btnEditModal = document.getElementById('btn-edit-modal');
const btnEditForm = document.getElementById('btn-edit-form');
const btnEditTitle = document.getElementById('btn-edit-title');
const btnEditLabel = document.getElementById('btn-edit-label');
const btnEditCommand = document.getElementById('btn-edit-command');
const btnEditDanger = document.getElementById('btn-edit-danger');
const btnEditErr = document.getElementById('btn-edit-err');
const btnEditParamsList = document.getElementById('btn-edit-params-list');
const btnTypeRadios = btnEditForm.querySelectorAll('input[name="btn-type"]');
const btnRunModal = document.getElementById('btn-run-modal');
const btnRunForm = document.getElementById('btn-run-form');
const btnRunTitle = document.getElementById('btn-run-title');
const btnRunFields = document.getElementById('btn-run-fields');
const btnRunErr = document.getElementById('btn-run-err');
let pendingRunButton = null;
let editingParams = [];

function getEditType() {
  const checked = btnEditForm.querySelector('input[name="btn-type"]:checked');
  return checked ? checked.value : 'instance';
}

function setEditType(type) {
  btnTypeRadios.forEach((r) => { r.checked = r.value === type; });
  syncEditTypeUi();
}

function syncEditTypeUi() {
  const isTpl = getEditType() === 'template';
  btnEditForm.querySelectorAll('.template-only').forEach((el) => {
    el.hidden = !isTpl;
  });
  btnEditCommand.placeholder = isTpl
    ? '例如：shell:echo ${paraA}'
    : '例如：shell:vcgencmd measure_temp';
}

btnTypeRadios.forEach((r) => r.addEventListener('change', syncEditTypeUi));

function renderEditParams() {
  btnEditParamsList.innerHTML = '';
  if (!editingParams.length) {
    btnEditParamsList.innerHTML = '<p class="muted">无参数。命令中写 <code>${参数名}</code> 后在此添加。</p>';
    return;
  }
  editingParams.forEach((param, index) => {
    const row = document.createElement('div');
    row.className = 'btn-param-row';
    row.innerHTML = `
      <input type="text" class="param-name" placeholder="参数名 paraA" value="${escapeHtml(param.name)}" maxlength="32" />
      <input type="text" class="param-label" placeholder="显示名（可选）" value="${escapeHtml(param.label)}" maxlength="40" />
      <input type="text" class="param-default" placeholder="默认值（可选）" value="${escapeHtml(param.default)}" maxlength="200" />
      <button type="button" class="ghost btn-sm danger-text param-remove" title="删除参数">×</button>`;
    row.querySelector('.param-remove').addEventListener('click', () => {
      editingParams.splice(index, 1);
      renderEditParams();
    });
    btnEditParamsList.appendChild(row);
  });
}

function collectEditParams() {
  if (getEditType() !== 'template') return [];
  const rows = btnEditParamsList.querySelectorAll('.btn-param-row');
  const out = [];
  const seen = new Set();
  for (const row of rows) {
    const name = row.querySelector('.param-name').value.trim();
    const label = row.querySelector('.param-label').value.trim();
    const def = row.querySelector('.param-default').value;
    if (!name) continue;
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) {
      throw new Error(`参数名无效：${name}`);
    }
    if (seen.has(name)) throw new Error(`参数名重复：${name}`);
    seen.add(name);
    out.push({ name, label: label || name, default: def });
  }
  if (out.length > 8) throw new Error('每个模板最多 8 个参数');
  return out;
}

function paramsSummary(btn) {
  if (!isTemplate(btn) || !btn.params?.length) return '';
  return ` · 参数 ${btn.params.map((p) => p.name).join(', ')}`;
}

function buildManageRow(btn, kind) {
  const row = document.createElement('div');
  row.className = 'btn-manage-row';
  row.dataset.id = btn.id;
  row.dataset.kind = kind;
  row.innerHTML = `
    <span class="drag-handle" role="button" tabindex="0" title="拖动排序" aria-label="拖动排序">≡</span>
    <div class="btn-manage-info">
      <strong>${escapeHtml(btn.label)}</strong>
      <code class="cmd-preview" title="${escapeHtml(btn.command)}">${escapeHtml(btn.command)}</code>
      <span class="muted manage-meta">${escapeHtml(paramsSummary(btn))}</span>
      ${btn.danger ? '<span class="badge danger-badge">危险</span>' : ''}
    </div>
    <div class="btn-manage-actions">
      <button type="button" class="ghost btn-sm" data-action="copy">复制</button>
      <button type="button" class="ghost btn-sm" data-action="edit">编辑</button>
      <button type="button" class="ghost btn-sm danger-text" data-action="delete">删除</button>
    </div>`;

  attachDragHandle(row.querySelector('.drag-handle'), row, btn, kind);

  row.querySelector('[data-action="edit"]').addEventListener('click', () => openButtonEditor(btn.id));
  row.querySelector('[data-action="copy"]').addEventListener('click', () => copyCommandButton(btn.id));
  row.querySelector('[data-action="delete"]').addEventListener('click', () => deleteCommandButton(btn.id));
  return row;
}

function renderManageList() {
  const { instances, templates } = splitButtons();
  btnManageInstances.innerHTML = instances.length ? '' : '<p class="muted">暂无命令。</p>';
  btnManageTemplates.innerHTML = templates.length ? '' : '<p class="muted">暂无模板。</p>';
  instances.forEach((btn) => btnManageInstances.appendChild(buildManageRow(btn, 'instance')));
  templates.forEach((btn) => btnManageTemplates.appendChild(buildManageRow(btn, 'template')));
}

async function reorderByDrag(sourceId, targetId, kind) {
  const { instances, templates } = splitButtons();
  const list = kind === 'template' ? [...templates] : [...instances];
  const from = list.findIndex((b) => b.id === sourceId);
  const to = list.findIndex((b) => b.id === targetId);
  if (from < 0 || to < 0 || from === to) return;
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item);
  if (kind === 'template') mergeButtons(instances, list);
  else mergeButtons(list, templates);
  btnManageErr.textContent = '';
  try {
    await persistCommandButtons();
    renderManageList();
  } catch (e) {
    btnManageErr.textContent = String(e.message || e);
    await loadCommandButtons();
    renderManageList();
  }
}

function openButtonManager() {
  if (!authenticated) { openLoginModal(); return; }
  btnManageErr.textContent = '';
  renderManageList();
  btnManageModal.hidden = false;
}

function closeButtonManager() {
  btnManageModal.hidden = true;
}

function openButtonEditor(id, template = null, forcedType = null) {
  editingButtonId = id || null;
  btnEditErr.textContent = '';
  const source = template || (editingButtonId ? commandButtons.find((b) => b.id === editingButtonId) : null);
  if (editingButtonId && !source) return;
  if (template) {
    btnEditTitle.textContent = '复制';
    btnEditLabel.value = source.label.length > 36 ? `${source.label.slice(0, 36)} 副本` : `${source.label} 副本`;
    btnEditCommand.value = source.command;
    btnEditDanger.checked = !!source.danger;
    editingParams = (source.params || []).map((p) => ({ ...p }));
    setEditType(isTemplate(source) ? 'template' : 'instance');
  } else if (editingButtonId && source) {
    btnEditTitle.textContent = isTemplate(source) ? '编辑模板' : '编辑命令';
    btnEditLabel.value = source.label;
    btnEditCommand.value = source.command;
    btnEditDanger.checked = !!source.danger;
    editingParams = (source.params || []).map((p) => ({ ...p }));
    setEditType(isTemplate(source) ? 'template' : 'instance');
  } else {
    btnEditTitle.textContent = forcedType === 'template' ? '添加模板' : '添加命令';
    btnEditLabel.value = '';
    btnEditCommand.value = '';
    btnEditDanger.checked = false;
    editingParams = [];
    setEditType(forcedType || 'instance');
  }
  renderEditParams();
  btnEditModal.hidden = false;
  setTimeout(() => btnEditLabel.focus(), 30);
}

function copyCommandButton(id) {
  const btn = commandButtons.find((b) => b.id === id);
  if (!btn) return;
  openButtonEditor(null, btn);
}

function openRunModal(btn) {
  pendingRunButton = btn;
  btnRunErr.textContent = '';
  btnRunTitle.textContent = btn.label;
  btnRunFields.innerHTML = '';
  const params = btn.params || [];
  if (!params.length) {
    const wrap = document.createElement('p');
    wrap.className = 'muted';
    wrap.textContent = '此模板未定义参数，将直接执行命令。';
    btnRunFields.appendChild(wrap);
  } else {
    params.forEach((param) => {
      const wrap = document.createElement('label');
      wrap.className = 'field-block';
      wrap.innerHTML = `
        <span class="field-label">${escapeHtml(param.label || param.name)} <code>\${${escapeHtml(param.name)}}</code></span>
        <input type="text" data-param-name="${escapeHtml(param.name)}" value="${escapeHtml(param.default || '')}" maxlength="200" />`;
      btnRunFields.appendChild(wrap);
    });
  }
  btnRunModal.hidden = false;
  const first = btnRunFields.querySelector('input');
  if (first) setTimeout(() => first.focus(), 30);
}

function closeRunModal() {
  btnRunModal.hidden = true;
  pendingRunButton = null;
}

function closeButtonEditor() {
  btnEditModal.hidden = true;
  editingButtonId = null;
}

async function deleteCommandButton(id) {
  const btn = commandButtons.find((b) => b.id === id);
  if (!btn) return;
  if (!window.confirm(`删除「${btn.label}」？`)) return;
  btnManageErr.textContent = '';
  commandButtons = commandButtons.filter((b) => b.id !== id);
  try {
    await persistCommandButtons();
    renderManageList();
  } catch (e) {
    btnManageErr.textContent = String(e.message || e);
    await loadCommandButtons();
    renderManageList();
  }
}

document.getElementById('btn-manage-commands').addEventListener('click', openButtonManager);
document.getElementById('btn-manage-close').addEventListener('click', closeButtonManager);
document.getElementById('btn-manage-add-instance').addEventListener('click', () => openButtonEditor(null, null, 'instance'));
document.getElementById('btn-manage-add-template').addEventListener('click', () => openButtonEditor(null, null, 'template'));
document.getElementById('btn-edit-param-add').addEventListener('click', () => {
  if (editingParams.length >= 8) {
    btnEditErr.textContent = '每个模板最多 8 个参数';
    return;
  }
  editingParams.push({ name: '', label: '', default: '' });
  renderEditParams();
});
document.getElementById('btn-edit-cancel').addEventListener('click', closeButtonEditor);
document.getElementById('btn-run-cancel').addEventListener('click', closeRunModal);
btnManageModal.addEventListener('click', (ev) => { if (ev.target === btnManageModal) closeButtonManager(); });
btnEditModal.addEventListener('click', (ev) => { if (ev.target === btnEditModal) closeButtonEditor(); });
btnRunModal.addEventListener('click', (ev) => { if (ev.target === btnRunModal) closeRunModal(); });

btnRunForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  btnRunErr.textContent = '';
  const btn = pendingRunButton;
  if (!btn) return;
  const values = {};
  btnRunFields.querySelectorAll('input[data-param-name]').forEach((input) => {
    values[input.dataset.paramName] = input.value;
  });
  const command = applyCommandParams(btn.command, values);
  if (btn.danger && !window.confirm(`确认执行 ${command}？`)) return;
  closeRunModal();
  await recordRecent(command, btn);
  runCommand(command);
});

btnEditForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  btnEditErr.textContent = '';
  const label = btnEditLabel.value.trim();
  const command = btnEditCommand.value.trim();
  const danger = btnEditDanger.checked;
  const type = getEditType();
  if (!label || !command) {
    btnEditErr.textContent = '请填写按钮文字和执行命令';
    return;
  }
  let params;
  try {
    params = collectEditParams();
  } catch (e) {
    btnEditErr.textContent = String(e.message || e);
    return;
  }
  const submitBtn = btnEditForm.querySelector('button[type="submit"]');
  const prevLabel = submitBtn ? submitBtn.textContent : '';
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = '保存中…';
  }
  const next = {
    id: editingButtonId || newButtonId(),
    type,
    label,
    command,
    danger,
    params,
  };
  if (editingButtonId) {
    commandButtons = commandButtons.map((b) => (b.id === editingButtonId ? next : b));
  } else {
    commandButtons = [...commandButtons, next];
  }
  try {
    await persistCommandButtons();
    closeButtonEditor();
    renderManageList();
  } catch (e) {
    btnEditErr.textContent = String(e.message || e);
    await loadCommandButtons();
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = prevLabel || '保存';
    }
  }
});

syncEditTypeUi();

// ---------------------------------------------------------------------------
// Terminal (xterm.js) — requires auth
// ---------------------------------------------------------------------------

let terminalReady = false;
function initTerminal() {
  if (terminalReady || !authenticated) return;
  terminalReady = true;

  const term = new window.Terminal({
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
    fontSize: 13,
    theme: { background: '#000000' },
    cursorBlink: true,
  });
  const fitAddon = new window.FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById('terminal'));
  fitAddon.fit();

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/shell`);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    term.writeln('\x1b[36m[connected]\x1b[0m');
    ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') term.write(ev.data);
    else term.write(new Uint8Array(ev.data));
  };
  ws.onclose = (ev) => {
    term.writeln(`\r\n\x1b[31m[disconnected ${ev.code}]\x1b[0m`);
    terminalReady = false;
    if (ev.code === 4401) {
      applyAuthState(false);
      openLoginModal();
    }
  };
  ws.onerror = () => term.writeln('\r\n\x1b[31m[ws error]\x1b[0m');

  term.onData((data) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data));
  });

  const resize = () => {
    fitAddon.fit();
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
    }
  };
  window.addEventListener('resize', resize);
  setTimeout(resize, 50);
}

// ---------------------------------------------------------------------------
// Monitor tab (public, default view) — Chart.js
// ---------------------------------------------------------------------------

const MAX_POINTS = 60;
let monitorReady = false;
let charts = {};

function makeChart(canvasId, label, color, unit = '%') {
  const ctx = document.getElementById(canvasId).getContext('2d');
  return new window.Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: color,
        backgroundColor: color + '33',
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.25,
        fill: true,
      }],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: {
          beginAtZero: true,
          ticks: { color: '#6b7280', callback: (v) => v + unit },
          grid: { color: 'rgba(0,0,0,0.08)' },
        },
      },
    },
  });
}

function pushPoint(chart, value) {
  const ts = new Date().toLocaleTimeString();
  chart.data.labels.push(ts);
  chart.data.datasets[0].data.push(value);
  while (chart.data.labels.length > MAX_POINTS) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update('none');
}

function humanBytes(n) {
  if (n == null) return '?';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 ? 1 : 0)} ${units[i]}`;
}

function renderDisks(disks) {
  const root = document.getElementById('disks');
  if (!disks || !disks.length) { root.innerHTML = '<p class="muted">无可读分区</p>'; return; }
  root.innerHTML = disks.map((d) => {
    const cls = d.percent > 90 ? 'danger' : d.percent > 75 ? 'warn' : '';
    return `
      <div class="disk">
        <div class="label">${d.mount} <span class="muted">(${d.fstype})</span></div>
        <div class="num">${humanBytes(d.used)} / ${humanBytes(d.total)} · ${d.percent.toFixed(1)}%</div>
        <div class="bar"><span class="${cls}" style="width:${d.percent}%"></span></div>
      </div>`;
  }).join('');
}

function renderProcs(top) {
  const tbody = document.getElementById('procs');
  if (!top || !top.length) { tbody.innerHTML = '<tr><td colspan="5" class="muted">无数据</td></tr>'; return; }
  tbody.innerHTML = top.map((p) => `
    <tr>
      <td>${p.pid}</td>
      <td>${p.user}</td>
      <td>${(p.name || '').replace(/</g, '&lt;')}</td>
      <td>${(p.cpu_pct || 0).toFixed(1)}</td>
      <td>${(p.mem_pct || 0).toFixed(1)}</td>
    </tr>`).join('');
}

function applyMonitor(snap) {
  if (snap.cpu_pct != null) pushPoint(charts.cpu, snap.cpu_pct);
  if (snap.memory && snap.memory.percent != null) pushPoint(charts.mem, snap.memory.percent);
  if (snap.temp_c != null) pushPoint(charts.temp, snap.temp_c);

  const nic = (snap.net || []).find((n) => n.rx_bps != null || n.tx_bps != null);
  const rxKB = nic && nic.rx_bps != null ? nic.rx_bps / 1024 : 0;
  const txKB = nic && nic.tx_bps != null ? nic.tx_bps / 1024 : 0;
  pushPoint(charts.net, +(rxKB + txKB).toFixed(2));
  document.getElementById('net-meta').textContent =
    `${nic ? nic.nic : '?'}  ↓${rxKB.toFixed(1)} KB/s  ↑${txKB.toFixed(1)} KB/s`;

  const load = snap.load ? snap.load.map((x) => x.toFixed(2)).join(' / ') : '?';
  const cores = (snap.cpu_per_core || []).map((v) => v.toFixed(0) + '%').join(' ');
  document.getElementById('cpu-meta').textContent = `load: ${load}   cores: ${cores || '?'}`;

  if (snap.memory) {
    document.getElementById('mem-meta').textContent =
      `used ${humanBytes(snap.memory.used)} / ${humanBytes(snap.memory.total)} (${snap.memory.percent.toFixed(1)}%)` +
      `  ·  swap ${humanBytes(snap.memory.swap_used)} / ${humanBytes(snap.memory.swap_total)} (${snap.memory.swap_percent.toFixed(1)}%)`;
  }

  document.getElementById('temp-meta').textContent =
    snap.temp_c != null ? `cur: ${snap.temp_c.toFixed(1)} °C` : 'cur: ?';

  renderDisks(snap.disks);
  renderProcs(snap.top);
}

function initMonitor() {
  if (monitorReady) return;
  monitorReady = true;

  charts.cpu = makeChart('chart-cpu', 'CPU%', '#059669', '%');
  charts.mem = makeChart('chart-mem', 'MEM%', '#2563eb', '%');
  charts.temp = makeChart('chart-temp', 'Temp', '#d97706', '°C');
  charts.net = makeChart('chart-net', 'KB/s', '#7c3aed', '');

  fetch('/api/monitor?history=60').then((r) => r.ok && r.json().then((snap) => {
    if (Array.isArray(snap.history)) snap.history.forEach(applyMonitor);
    applyMonitor(snap);
  }));

  let backoff = 1000;
  function connect() {
    const es = new EventSource('/api/monitor/stream');
    es.onmessage = (ev) => {
      try { applyMonitor(JSON.parse(ev.data)); backoff = 1000; }
      catch (e) { /* ignore */ }
    };
    es.onerror = () => {
      es.close();
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
  }
  connect();
}

// The monitor tab is the default landing view — initialise immediately so
// charts start populating without waiting for a click.
initMonitor();
