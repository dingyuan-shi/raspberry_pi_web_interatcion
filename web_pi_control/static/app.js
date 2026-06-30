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

document.querySelectorAll('.quick button').forEach((btn) => {
  btn.addEventListener('click', () => {
    if (!authenticated) { openLoginModal(); return; }
    const cmd = btn.dataset.cmd;
    if (btn.classList.contains('danger') && !window.confirm(`确认执行 ${cmd}？`)) return;
    runCommand(cmd);
  });
});

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
