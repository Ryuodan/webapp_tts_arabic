'use strict';

// ── Built-in voices ───────────────────────────────────────────
// `voice` on /synthesize is a closed set — the ids under voices/ on the server — so it
// renders as a dropdown instead of a free-text box the caller has to guess at. The list
// here is what the repo ships; refreshVoices() swaps in whatever the worker actually
// loaded, so a voice dropped into voices/ needs no edit to this file.
let VOICE_IDS = ['abeer', 'ahmed'];
const VOICE_LABELS = { abeer: 'voice.abeer', ahmed: 'voice.ahmed' };

function voiceOptions() {
  const opts = [{ value: '', get label() { return t('voice.none'); } }];
  for (const id of VOICE_IDS) {
    const key = VOICE_LABELS[id];
    opts.push({ value: id, label: key ? `${id} — ${t(key)}` : id });
  }
  return opts;
}

// ── Endpoint catalogue ────────────────────────────────────────
// One spec per endpoint drives everything on the page: the parameter table,
// the curl snippet and the live try-it form. Adding an endpoint = adding an entry.
//
// field.in — 'path' | 'query' | 'body' (default). encoding — 'form' | 'json' | null.
const ENDPOINTS = [
  {
    method: 'GET',
    path: '/api/status',
    get title() { return t('ep.status.title'); },
    get desc() { return t('ep.status.desc'); },
    fields: [],
  },
  {
    method: 'POST',
    path: '/api/transcribe',
    get title() { return t('ep.tr.title'); },
    get desc() { return t('ep.tr.desc'); },
    // Pinned in workers/transcribe_server.py — keep the two in step if it ever changes.
    model: {
      name: 'NAMAA-Space/cohere-transcribe-arabic-07-2026-int8',
      url: 'https://huggingface.co/NAMAA-Space/cohere-transcribe-arabic-07-2026-int8',
      get note() { return t('ep.tr.model'); },
    },
    encoding: 'form',
    fields: [
      { name: 'audio',       type: 'file',   required: true, get note() { return t('ep.tr.audio'); } },
      { name: 'language',    type: 'select', options: ['ar', 'en'], value: 'ar', get note() { return t('ep.tr.lang'); } },
      { name: 'punctuation', type: 'select', options: ['true', 'false'], value: 'true', get note() { return t('ep.tr.punct'); } },
    ],
    returns: '{ text, language, filename, duration_s, elapsed_s, rtf, sample_rate }',
  },
  {
    method: 'POST',
    path: '/api/{model}/synthesize',
    get title() { return t('ep.synth.title'); },
    get desc() { return t('ep.synth.desc'); },
    encoding: 'form',
    fields: [
      { name: 'model',   type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base'], value: 'omnivoice_ft' },
      { name: 'text',    type: 'text',   required: true, value: 'مرحباً، كيف حالك؟' },
      { name: 'dialect', type: 'select', options: ['msa', 'saudi', 'egyptian'], value: 'msa' },
      { name: 'voice',   type: 'select', get options() { return voiceOptions(); }, value: '',
        get note() { return t('ep.synth.voice'); } },
      { name: 'gender',  type: 'select', options: ['', 'male', 'female'], value: '', get note() { return t('ep.synth.gender'); } },
      { name: 'age',     type: 'select', options: ['', 'young', 'middle', 'old'], value: '' },
    ],
    returns: '{ filename, model, model_input, duration_s, elapsed_s, rtf, sample_rate }',
  },
  {
    method: 'POST',
    path: '/api/{model}/load',
    get title() { return t('ep.load.title'); },
    get desc() { return t('ep.load.desc'); },
    fields: [
      { name: 'model', type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'transcribe' },
    ],
  },
  {
    method: 'GET',
    path: '/api/{model}/status',
    get title() { return t('ep.one.title'); },
    get desc() { return t('ep.one.desc'); },
    fields: [
      { name: 'model', type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'transcribe' },
    ],
  },
  {
    method: 'GET',
    path: '/api/{model}/history',
    get title() { return t('ep.hist.title'); },
    get desc() { return t('ep.hist.desc'); },
    fields: [
      { name: 'model', type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'transcribe' },
      { name: 'limit', type: 'text', in: 'query', value: '10' },
    ],
    returns: '[ { filename, model, text, params, duration_s, rtf, mtime, size_bytes } ]',
  },
  {
    method: 'POST',
    path: '/api/prepare',
    get title() { return t('ep.prep.title'); },
    get desc() { return t('ep.prep.desc'); },
    encoding: 'json',
    fields: [
      { name: 'text',       type: 'text',   required: true, value: 'الموعد 15/3/2026 الساعة 9:30 صباحاً' },
      { name: 'dialect',    type: 'select', options: ['msa', 'saudi', 'egyptian'], value: 'msa' },
      { name: 'normalize',  type: 'select', options: ['true', 'false'], value: 'true', json: 'bool' },
      { name: 'diacritize', type: 'select', options: ['false', 'true'], value: 'false', json: 'bool' },
    ],
    returns: '{ original, normalized, diacritized, text, notes }',
  },
  {
    method: 'POST',
    path: '/api/compose',
    get title() { return t('ep.compose.title'); },
    get desc() { return t('ep.compose.desc'); },
    encoding: 'json',
    fields: [
      { name: 'job',     type: 'select', required: true,
        options: ['customer_service', 'booking', 'storytelling', 'announcement'], value: 'customer_service' },
      { name: 'dialect', type: 'select', options: ['msa', 'saudi', 'egyptian'], value: 'msa' },
      { name: 'gender',  type: 'select', options: ['', 'male', 'female'], value: '' },
      { name: 'age',     type: 'select', options: ['', 'young', 'middle', 'old'], value: '' },
      { name: 'brief',   type: 'text',   value: '' },
    ],
    returns: '{ text, dialect, gender, age, omnivoice_instruct, notes }',
  },
  {
    method: 'GET',
    path: '/audio/{model}/{filename}',
    get title() { return t('ep.audio.title'); },
    get desc() { return t('ep.audio.desc'); },
    fields: [
      { name: 'model',    type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'omnivoice_ft' },
      { name: 'filename', type: 'text',   in: 'path', value: 'omnivoice_xxxxxxxxxxxx.wav' },
    ],
    noTry: true,
  },
];

const $ = id => document.getElementById(id);
const str = v => (v === null || v === undefined) ? '' : String(v);
const escapeHtml = v => str(v).replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// A select option is either a bare value or a {value, label} pair with a friendlier name.
const isPair = o => o !== null && typeof o === 'object';
const optValue = o => isPair(o) ? o.value : o;
const optLabel = o => (isPair(o) ? o.label : o) || t('api.emptyOpt');

const fieldsIn = (spec, where) => spec.fields.filter(f => (f.in || 'body') === where);
const slug = spec => `${spec.method}-${spec.path}`.replace(/[^a-z0-9]+/gi, '-').toLowerCase();

// ── Request building ──────────────────────────────────────────
// Reads the rendered form back out; used by both the live call and the curl snippet.
function readValues(spec, form) {
  const out = {};
  for (const f of spec.fields) {
    const el = form ? form.querySelector(`[name="${f.name}"]`) : null;
    out[f.name] = f.type === 'file' ? (el && el.files[0]) || null
                                    : (el ? el.value : str(f.value));
  }
  return out;
}

function buildUrl(spec, values) {
  let path = spec.path.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(str(values[k])));
  const query = fieldsIn(spec, 'query')
    .filter(f => str(values[f.name]).trim())
    .map(f => `${f.name}=${encodeURIComponent(values[f.name])}`);
  return query.length ? `${path}?${query.join('&')}` : path;
}

// Body fields, minus the ones the user left empty (the server applies its own defaults).
function bodyEntries(spec, values) {
  return fieldsIn(spec, 'body').filter(f => {
    const v = values[f.name];
    return f.type === 'file' ? v instanceof File : str(v).trim() !== '';
  });
}

function buildBody(spec, values) {
  const entries = bodyEntries(spec, values);
  if (!entries.length) return undefined;
  if (spec.encoding === 'json') {
    const payload = {};
    for (const f of entries) {
      payload[f.name] = f.json === 'bool' ? values[f.name] === 'true' : values[f.name];
    }
    return JSON.stringify(payload);
  }
  const fd = new FormData();
  for (const f of entries) {
    const v = values[f.name];
    v instanceof File ? fd.append(f.name, v, v.name) : fd.append(f.name, v);
  }
  return fd;
}

function buildCurl(spec, values) {
  const origin = window.location.origin;
  const parts = [`curl -X ${spec.method} '${origin}${buildUrl(spec, values)}'`];
  const entries = bodyEntries(spec, values);

  if (spec.encoding === 'json' && entries.length) {
    parts.push(`-H 'Content-Type: application/json'`);
    parts.push(`-d '${buildBody(spec, values)}'`);
  } else {
    for (const f of entries) {
      const v = values[f.name];
      parts.push(f.type === 'file'
        ? `-F '${f.name}=@${v instanceof File ? v.name : 'audio.wav'}'`
        : `-F '${f.name}=${v}'`);
    }
  }
  return parts.join(' \\\n     ');
}

// ── Rendering ─────────────────────────────────────────────────
function fieldControlHtml(f) {
  // Audio fields get a recorder beside the picker so the endpoint is testable without
  // first producing a file on disk. The button reveals itself only if the mic is usable.
  if (f.type === 'file')   return `
    <span class="api-file">
      <input type="file" name="${f.name}" accept="audio/*">
      <button type="button" class="api-mic" hidden>${t('tr.record')}</button>
      <span class="api-mic-state"></span>
    </span>`;
  if (f.type === 'select') return `<select name="${f.name}">${f.options.map(o =>
    `<option value="${escapeHtml(optValue(o))}" ${optValue(o) === f.value ? 'selected' : ''}>${escapeHtml(optLabel(o))}</option>`
  ).join('')}</select>`;
  return `<input type="text" name="${f.name}" value="${escapeHtml(f.value)}" dir="auto">`;
}

function fieldRowHtml(f) {
  const where = f.in && f.in !== 'body' ? `<span class="api-in">${f.in}</span>` : '';
  return `
    <label class="api-field">
      <span class="api-field-name">
        ${escapeHtml(f.name)}${f.required ? '<em>*</em>' : ''} ${where}
      </span>
      ${fieldControlHtml(f)}
      ${f.note ? `<small>${escapeHtml(f.note)}</small>` : ''}
    </label>
  `;
}

function cardHtml(spec) {
  const id = slug(spec);
  return `
    <section class="api-card" id="card-${id}">
      <div class="api-card-head">
        <span class="api-method m-${spec.method.toLowerCase()}">${spec.method}</span>
        <code class="api-path">${escapeHtml(spec.path)}</code>
        <span class="api-title">${escapeHtml(spec.title)}</span>
      </div>
      <p class="api-desc">${escapeHtml(spec.desc)}</p>
      ${spec.model ? `
        <div class="api-model">
          <span>${t('api.model')}</span>
          <a href="${escapeHtml(spec.model.url)}" target="_blank" rel="noopener noreferrer"
             dir="ltr">${escapeHtml(spec.model.name)}</a>
          ${spec.model.note ? `<small>${escapeHtml(spec.model.note)}</small>` : ''}
        </div>` : ''}
      ${spec.returns ? `<div class="api-returns"><span>${t('api.returns')}</span><code>${escapeHtml(spec.returns)}</code></div>` : ''}
      <form class="api-form" data-id="${id}">
        ${spec.fields.map(fieldRowHtml).join('')}
        ${spec.noTry ? '' : `<button type="submit" class="btn-prep api-run">${t('api.try')}</button>`}
      </form>
      <div class="api-curl">
        <div class="api-curl-head">
          <span>curl</span>
          <button type="button" class="btn-ghost btn-xs api-copy">${t('api.copy')}</button>
        </div>
        <pre dir="ltr"><code class="api-curl-body"></code></pre>
      </div>
      <div class="api-response" hidden>
        <div class="api-response-head"><span class="api-status"></span><span class="api-timing"></span></div>
        <pre dir="ltr"><code class="api-response-body"></code></pre>
        <div class="api-response-audio"></div>
      </div>
    </section>
  `;
}

// ── Live call ─────────────────────────────────────────────────
async function runEndpoint(spec, card) {
  const form = card.querySelector('.api-form');
  const btn = card.querySelector('.api-run');
  const box = card.querySelector('.api-response');
  const values = readValues(spec, form);

  const missing = spec.fields.find(f => f.required &&
    (f.type === 'file' ? !(values[f.name] instanceof File) : !str(values[f.name]).trim()));
  if (missing) {
    showResponse(card, 0, t('api.missingField', { name: missing.name }), 0);
    return;
  }

  btn.disabled = true;
  btn.textContent = t('api.running');
  box.hidden = false;
  const t0 = performance.now();
  try {
    const init = { method: spec.method };
    const body = buildBody(spec, values);
    if (body !== undefined) {
      init.body = body;
      if (spec.encoding === 'json') init.headers = { 'Content-Type': 'application/json' };
    }
    const r = await fetch(buildUrl(spec, values), init);
    const raw = await r.text();
    let parsed = null;
    try { parsed = JSON.parse(raw); } catch { /* error bodies are plain text */ }
    showResponse(card, r.status, parsed ? JSON.stringify(parsed, null, 2) : raw,
                 performance.now() - t0, parsed);
  } catch (e) {
    showResponse(card, 0, String(e.message || e), performance.now() - t0);
  } finally {
    btn.disabled = false;
    btn.textContent = t('api.try');
  }
}

function showResponse(card, status, text, ms, parsed = null) {
  const box = card.querySelector('.api-response');
  box.hidden = false;
  const ok = status >= 200 && status < 300;
  const statusEl = box.querySelector('.api-status');
  statusEl.textContent = status ? `HTTP ${status}` : t('api.failed');
  statusEl.className = `api-status ${ok ? 'ok' : 'err'}`;
  box.querySelector('.api-timing').textContent = ms ? `${(ms / 1000).toFixed(2)}s` : '';
  box.querySelector('.api-response-body').textContent = text;

  // Any response naming a saved file gets a player for it.
  const audio = box.querySelector('.api-response-audio');
  const file = parsed && parsed.filename && parsed.model
    ? `/audio/${parsed.model}/${parsed.filename}` : '';
  audio.innerHTML = file ? `<audio controls src="${escapeHtml(file)}"></audio>` : '';
}

// ── Mic capture ───────────────────────────────────────────────
// The recorded File is pushed into the real <input type="file">, so readValues /
// buildBody / buildCurl keep working on `el.files[0]` with no special case for it.
function wireMic(card, onChange) {
  const input = card.querySelector('input[type="file"]');
  const btn = card.querySelector('.api-mic');
  // No mic (or an insecure origin) leaves the button hidden — the picker still works.
  if (!input || !btn || !MicRecorder.supported() || !window.isSecureContext) return;

  const state = card.querySelector('.api-mic-state');
  let handle = null;
  let timer = null;

  const idle = () => {
    btn.textContent = t('tr.record');
    btn.classList.remove('recording');
    clearInterval(timer);
    timer = null;
  };

  btn.addEventListener('click', async () => {
    if (handle) {                      // second click: stop and hand over the file
      const active = handle;
      handle = null;
      idle();
      try {
        const file = await active.stop();
        setInputFile(input, file);
        state.textContent = `✓ ${file.name} — ${Math.round(file.size / 1024)}KB`;
        onChange();                    // refresh the curl snippet with the new filename
      } catch (e) {
        state.textContent = e.message;
      }
      return;
    }

    state.textContent = '';
    try {
      handle = await MicRecorder.start();
    } catch (e) {
      state.textContent = e.message;   // already an Arabic, actionable reason
      return;
    }
    btn.textContent = t('tr.stop');
    btn.classList.add('recording');
    timer = setInterval(() => {
      state.textContent = `● ${MicRecorder.fmtElapsed(Date.now() - handle.startedAt)}`;
    }, 250);
  });
}

// ── Init ──────────────────────────────────────────────────────
// The cards are template strings, not data-i18n nodes, so a language flip rebuilds them
// wholesale. Any recorded clip or typed value is discarded with the old markup — an
// acceptable trade on a playground, and the alternative (tagging every generated node)
// would not survive the next endpoint added to the catalogue.
function render() {
  $('api-base').textContent = window.location.origin;
  $('api-list').innerHTML = ENDPOINTS.map(cardHtml).join('');

  for (const spec of ENDPOINTS) {
    const card = $(`card-${slug(spec)}`);
    const form = card.querySelector('.api-form');
    const curl = card.querySelector('.api-curl-body');
    const refresh = () => { curl.textContent = buildCurl(spec, readValues(spec, form)); };

    refresh();
    wireMic(card, refresh);
    form.addEventListener('input', refresh);
    form.addEventListener('change', refresh);
    form.addEventListener('submit', e => {
      e.preventDefault();
      if (!spec.noTry) runEndpoint(spec, card);
    });
    card.querySelector('.api-copy').addEventListener('click', e => {
      navigator.clipboard.writeText(curl.textContent);
      e.currentTarget.textContent = t('api.copied');
      setTimeout(() => { e.currentTarget.textContent = t('api.copy'); }, 1500);
    });
  }
}

// The worker reports the voices it loaded off disk; anything else leaves the bundled
// list standing, so an offline worker still shows a usable dropdown.
function refreshVoices() {
  return fetch('/api/omnivoice_ft/status')
    .then(r => r.json())
    .then(health => {
      const ids = Array.isArray(health.voices) ? health.voices : [];
      if (!ids.length || ids.join() === VOICE_IDS.join()) return;
      VOICE_IDS = ids;
      render();                       // repaints every card; only fires when the list differs
    })
    .catch(() => {});
}

function init() {
  I18N.apply();                       // paint the stored language before the first render
  render();
  refreshVoices();

  const toggle = $('lang-toggle');
  if (toggle) toggle.addEventListener('click', () => I18N.set(I18N.other()));
  document.addEventListener('languagechange', () => { render(); I18N.apply(); });
}

document.addEventListener('DOMContentLoaded', init);
