'use strict';

// Request-log console. Everything on the page comes from two endpoints: /api/logs/stats
// (the window's aggregates) and /api/logs (the rows themselves, bodies included — so
// expanding a row costs no round trip).

const PAGE_SIZE = 50;
const AUTO_REFRESH_MS = 10_000;

const state = {
  hours: 24,          // 0 = everything retained
  route: '',
  status: '',
  q: '',
  items: [],
  total: 0,
  stats: null,
  open: new Set(),    // ids of the expanded rows, kept across refreshes
  timer: null,
};

const $ = id => document.getElementById(id);
const escapeHtml = v => String(v ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ── Formatting ────────────────────────────────────────────────
const fmtMs = ms => (ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 2)}s` : `${Math.round(ms)}ms`);

function fmtBytes(n) {
  if (!n) return '0';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n < 10 && i ? n.toFixed(1) : Math.round(n)}${units[i]}`;
}

const fmtClock = ts => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
const fmtStamp = ts => new Date(ts * 1000).toLocaleString([], { hour12: false });

function fmtAgo(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60)    return `${Math.round(s)}${t('ago.s')}`;
  if (s < 3600)  return `${Math.round(s / 60)}${t('ago.m')}`;
  if (s < 86400) return `${Math.round(s / 3600)}${t('ago.h')}`;
  return `${Math.round(s / 86400)}${t('ago.d')}`;
}

const asText = value => (value === null || value === undefined ? ''
  : typeof value === 'string' ? value : JSON.stringify(value, null, 2));

// ── Fetching ──────────────────────────────────────────────────
async function api(path, init) {
  const r = await fetch(path, init);
  const raw = await r.text();
  let body = null;
  try { body = JSON.parse(raw); } catch { /* error bodies may be plain text */ }
  if (!r.ok) {
    const detail = body && body.detail ? body.detail : raw;
    throw Object.assign(new Error(detail || `HTTP ${r.status}`), { status: r.status });
  }
  return body;
}

function banner(message) {
  const el = $('logs-banner');
  el.hidden = !message;
  el.textContent = message || '';
}

function query(extra) {
  const params = new URLSearchParams({ hours: String(state.hours) });
  if (state.route)  params.set('route', state.route);
  if (state.status) params.set('status', state.status);
  if (state.q)      params.set('q', state.q);
  for (const [k, v] of Object.entries(extra || {})) params.set(k, String(v));
  return params.toString();
}

async function loadStats() {
  state.stats = await api(`/api/logs/stats?hours=${state.hours}`);
  renderStats();
}

async function loadRows(append) {
  const offset = append ? state.items.length : 0;
  const page = await api(`/api/logs?${query({ limit: PAGE_SIZE, offset })}`);
  state.items = append ? state.items.concat(page.items) : page.items;
  state.total = page.total;
  renderRows();
}

async function refresh(append) {
  try {
    await Promise.all([loadStats(), loadRows(append)]);
    banner('');
  } catch (e) {
    banner(e.status === 503 ? t('logs.disabled') : `${t('logs.failed')} — ${e.message}`);
  }
}

// ── Aggregates ────────────────────────────────────────────────
function tileHtml(label, value, sub, bad) {
  return `
    <div class="logs-tile${bad ? ' bad' : ''}">
      <div class="logs-tile-label">${escapeHtml(label)}</div>
      <div class="logs-tile-value">${escapeHtml(value)}</div>
      ${sub ? `<div class="logs-tile-sub">${escapeHtml(sub)}</div>` : ''}
    </div>`;
}

function renderStats() {
  const s = state.stats;
  if (!s) return;
  const k = s.totals;

  $('logs-stored').textContent = t('logs.stored', { n: s.stored_rows, cap: s.retention_rows });
  $('logs-tiles').innerHTML = [
    tileHtml(t('logs.total'), String(k.count)),
    tileHtml(t('logs.errors'), String(k.errors), `${(k.error_rate * 100).toFixed(1)}%`, k.errors > 0),
    tileHtml(t('logs.avg'), fmtMs(k.avg_ms)),
    tileHtml(t('logs.p50'), fmtMs(k.p50_ms)),
    tileHtml(t('logs.p95'), fmtMs(k.p95_ms)),
    tileHtml(t('logs.max'), fmtMs(k.max_ms)),
    tileHtml(t('logs.traffic'), `${fmtBytes(k.req_bytes)} / ${fmtBytes(k.resp_bytes)}`),
  ].join('');

  renderTimeline(s.timeline);
  renderEndpoints(s.endpoints);
  renderRouteFilter(s.endpoints);
}

function renderTimeline(buckets) {
  const peak = Math.max(1, ...buckets.map(b => b.count));
  const bars = buckets.map(b => {
    if (!b.count) return `<div class="logs-bar empty" title="0"></div>`;
    const height = (b.count / peak) * 100;
    const errShare = b.errors / b.count * 100;
    const title = `${fmtStamp(b.start)} — ${b.count} (${b.errors} err)`;
    return `
      <div class="logs-bar" title="${escapeHtml(title)}">
        <div style="height:${height}%; display:flex; flex-direction:column; justify-content:flex-end">
          <div class="logs-bar-ok" style="height:${100 - errShare}%"></div>
          <div class="logs-bar-err" style="height:${errShare}%"></div>
        </div>
      </div>`;
  }).join('');
  const first = buckets[0], last = buckets[buckets.length - 1];
  $('logs-timeline').innerHTML = bars + `
    <div class="logs-axis">
      <span>${escapeHtml(fmtStamp(first.start))}</span>
      <span>${escapeHtml(fmtStamp(last.start + last.width_s))}</span>
    </div>`;
}

function renderEndpoints(endpoints) {
  const head = `
    <tr>
      <th>${t('logs.col.endpoint')}</th><th>${t('logs.col.count')}</th><th>${t('logs.col.errors')}</th>
      <th>${t('logs.col.avg')}</th><th>${t('logs.col.p95')}</th><th>${t('logs.col.last')}</th>
    </tr>`;
  const rows = endpoints.map(e => `
    <tr>
      <td class="route">${escapeHtml(e.method)} ${escapeHtml(e.route)}</td>
      <td class="num">${e.count}</td>
      <td class="num${e.errors ? ' bad' : ''}">${e.errors}</td>
      <td class="num">${escapeHtml(fmtMs(e.avg_ms))}</td>
      <td class="num">${escapeHtml(fmtMs(e.p95_ms))}</td>
      <td class="num">${escapeHtml(fmtAgo(e.last_ts))}</td>
    </tr>`).join('');
  $('logs-endpoints').innerHTML = head + (rows ||
    `<tr><td colspan="6" class="logs-empty">${t('logs.empty')}</td></tr>`);
}

function renderRouteFilter(endpoints) {
  const routes = [...new Set(endpoints.map(e => e.route))].sort();
  // A route filtered on but absent from this window must stay selectable, or changing
  // the window would silently drop the filter along with its rows.
  if (state.route && !routes.includes(state.route)) routes.push(state.route);
  $('logs-route').innerHTML = `<option value="">${t('logs.allRoutes')}</option>` + routes.map(r =>
    `<option value="${escapeHtml(r)}" ${r === state.route ? 'selected' : ''}>${escapeHtml(r)}</option>`
  ).join('');
}

// ── Request rows ──────────────────────────────────────────────
function detailHtml(item) {
  const audio = item.response && item.response.filename && item.response.model
    ? `/audio/${encodeURIComponent(item.response.model)}/${encodeURIComponent(item.response.filename)}`
    : '';
  const block = (label, value, cls) => `
    <div>
      <div class="logs-block-label">${escapeHtml(label)}</div>
      <pre class="${cls || ''}">${escapeHtml(asText(value) || t('logs.noBody'))}</pre>
    </div>`;

  return `
    <div class="logs-detail">
      <div class="logs-detail-meta">
        <span><b>${t('logs.col.time')}:</b> ${escapeHtml(fmtStamp(item.ts))}</span>
        <span><b>${t('logs.col.took')}:</b> ${escapeHtml(fmtMs(item.duration_ms))}</span>
        <span><b>${t('logs.sizes')}:</b> ${fmtBytes(item.req_bytes)} / ${fmtBytes(item.resp_bytes)}</span>
        <span><b>${t('logs.client')}:</b> ${escapeHtml(item.client || '—')}</span>
        <span><b>${t('logs.agent')}:</b> ${escapeHtml(item.user_agent || '—')}</span>
      </div>
      ${block(t('logs.input'), item.request)}
      ${block(t('logs.output'), item.response)}
      ${item.error ? block(t('logs.errorLabel'), item.error, 'err') : ''}
      ${audio ? `<audio controls src="${escapeHtml(audio)}"></audio>` : ''}
    </div>`;
}

function rowHtml(item) {
  const open = state.open.has(item.id);
  return `
    <div class="logs-row${open ? ' open' : ''}" data-id="${item.id}">
      <button type="button" class="logs-row-head">
        <span class="logs-time">${escapeHtml(fmtClock(item.ts))}</span>
        <span class="logs-method m-${escapeHtml(item.method.toLowerCase())}">${escapeHtml(item.method)}</span>
        <span class="logs-path">${escapeHtml(item.path)}</span>
        <span class="logs-status ${item.ok ? 'ok' : 'err'}">${item.status}</span>
        <span class="logs-took">${escapeHtml(fmtMs(item.duration_ms))}</span>
      </button>
      ${open ? detailHtml(item) : ''}
    </div>`;
}

function renderRows() {
  const box = $('logs-rows');
  box.innerHTML = state.items.length
    ? state.items.map(rowHtml).join('')
    : `<div class="logs-empty">${t('logs.empty')}</div>`;

  $('logs-count').textContent = state.total
    ? t('logs.showing', { shown: state.items.length, total: state.total }) : '';

  const remaining = state.total - state.items.length;
  const more = $('logs-more');
  more.hidden = remaining <= 0;
  more.textContent = t('logs.loadMore', { n: remaining });
}

function toggleRow(id) {
  state.open.has(id) ? state.open.delete(id) : state.open.add(id);
  renderRows();
}

// ── Wiring ────────────────────────────────────────────────────
function setAuto(on) {
  clearInterval(state.timer);
  state.timer = on ? setInterval(() => refresh(false), AUTO_REFRESH_MS) : null;
}

function debounce(fn, ms) {
  let handle = null;
  return (...args) => {
    clearTimeout(handle);
    handle = setTimeout(() => fn(...args), ms);
  };
}

function init() {
  I18N.apply();

  $('logs-windows').addEventListener('click', e => {
    const btn = e.target.closest('button[data-hours]');
    if (!btn) return;
    state.hours = Number(btn.dataset.hours);
    [...$('logs-windows').children].forEach(b => b.classList.toggle('on', b === btn));
    refresh(false);
  });

  $('logs-refresh').addEventListener('click', () => refresh(false));
  $('logs-auto').addEventListener('change', e => setAuto(e.target.checked));
  $('logs-more').addEventListener('click', () => refresh(true));

  $('logs-route').addEventListener('change', e => { state.route = e.target.value; refresh(false); });
  $('logs-status').addEventListener('change', e => { state.status = e.target.value; refresh(false); });
  $('logs-q').addEventListener('input', debounce(e => {
    state.q = e.target.value.trim();
    refresh(false);
  }, 300));

  // Only the header toggles: a click inside an open row belongs to the audio player or
  // to selecting text out of the payloads.
  $('logs-rows').addEventListener('click', e => {
    const head = e.target.closest('.logs-row-head');
    if (head) toggleRow(Number(head.closest('.logs-row').dataset.id));
  });

  $('logs-clear').addEventListener('click', async () => {
    if (!confirm(t('logs.confirmClear'))) return;
    try {
      const { deleted } = await api('/api/logs', { method: 'DELETE' });
      state.open.clear();
      banner('');
      alert(t('logs.cleared', { n: deleted }));
    } catch (e) {
      banner(`${t('logs.failed')} — ${e.message}`);
    }
    refresh(false);
  });

  // Nothing here re-fetches on a language flip: the labels live in the rendered markup,
  // so replaying the render off the cached payloads is enough.
  document.addEventListener('languagechange', () => {
    I18N.apply();
    renderStats();
    renderRows();
  });
  const toggle = $('lang-toggle');
  if (toggle) toggle.addEventListener('click', () => I18N.set(I18N.other()));

  refresh(false);
}

document.addEventListener('DOMContentLoaded', init);
