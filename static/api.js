'use strict';

// ── Endpoint catalogue ────────────────────────────────────────
// One spec per endpoint drives everything on the page: the parameter table,
// the curl snippet and the live try-it form. Adding an endpoint = adding an entry.
//
// field.in — 'path' | 'query' | 'body' (default). encoding — 'form' | 'json' | null.
const ENDPOINTS = [
  {
    method: 'GET',
    path: '/api/status',
    title: 'حالة جميع العمّال',
    desc: 'حالة كل نموذج: هل العامل يعمل، وهل حُمِّل النموذج في الذاكرة بعد.',
    fields: [],
  },
  {
    method: 'POST',
    path: '/api/transcribe',
    title: 'تفريغ صوتي (Cohere Transcribe Arabic INT8)',
    desc: 'صوت ← نص عربي أو إنجليزي. يقبل wav/mp3/m4a/webm ويعيد أخذ العينات إلى 16kHz تلقائياً. '
        + 'المقاطع الأطول من نافذة النموذج تُقسَّم وتُدمج نتائجها تلقائياً.',
    // Pinned in workers/transcribe_server.py — keep the two in step if it ever changes.
    model: {
      name: 'NAMAA-Space/cohere-transcribe-arabic-07-2026-int8',
      url: 'https://huggingface.co/NAMAA-Space/cohere-transcribe-arabic-07-2026-int8',
      note: 'نسخة NAMAA-Space المكمَّمة (INT8) من نموذج Cohere للتفريغ العربي',
    },
    encoding: 'form',
    fields: [
      { name: 'audio',       type: 'file',   required: true, note: 'ملف صوتي — يخضع لحد حجم الطلب في الخادم' },
      { name: 'language',    type: 'select', options: ['ar', 'en'], value: 'ar', note: 'النموذج عربي/إنجليزي فقط' },
      { name: 'punctuation', type: 'select', options: ['true', 'false'], value: 'true', note: 'false ⇐ نص بلا ترقيم' },
    ],
    returns: '{ text, language, filename, duration_s, elapsed_s, rtf, sample_rate }',
  },
  {
    method: 'POST',
    path: '/api/{model}/synthesize',
    title: 'توليد كلام',
    desc: 'نص ← ملف wav. المعاملات الإضافية تختلف بين النموذجين: '
        + 'الاسمان أدناه نسختان من OmniVoice (المحسّنة والأصلية) تتشاركان نفس العامل.',
    encoding: 'form',
    fields: [
      { name: 'model',   type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base'], value: 'omnivoice_ft' },
      { name: 'text',    type: 'text',   required: true, value: 'مرحباً، كيف حالك؟' },
      { name: 'dialect', type: 'select', options: ['msa', 'saudi', 'egyptian'], value: 'msa' },
      { name: 'voice',   type: 'text',   value: '', note: 'اسم صوت مدمج، أو فارغ لصوت النموذج' },
      { name: 'gender',  type: 'select', options: ['', 'male', 'female'], value: '', note: 'فارغ = اختيار النموذج' },
      { name: 'age',     type: 'select', options: ['', 'young', 'middle', 'old'], value: '' },
    ],
    returns: '{ filename, model, model_input, duration_s, elapsed_s, rtf, sample_rate }',
  },
  {
    method: 'POST',
    path: '/api/{model}/load',
    title: 'تحميل نموذج مسبقاً',
    desc: 'يحمّل أوزان النموذج في الذاكرة الآن بدل انتظار أول طلب. مفيد لتفادي بطء أول استدعاء.',
    fields: [
      { name: 'model', type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'transcribe' },
    ],
  },
  {
    method: 'GET',
    path: '/api/{model}/status',
    title: 'حالة نموذج واحد',
    desc: 'نفس محتوى ‎/api/status‎ لكن لنموذج بعينه.',
    fields: [
      { name: 'model', type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'transcribe' },
    ],
  },
  {
    method: 'GET',
    path: '/api/{model}/history',
    title: 'سجل المخرجات',
    desc: 'آخر الملفات المحفوظة على الخادم مع مدخلاتها. لـ transcribe يحتوي الحقل text على النص المُفرَّغ.',
    fields: [
      { name: 'model', type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'transcribe' },
      { name: 'limit', type: 'text', in: 'query', value: '10' },
    ],
    returns: '[ { filename, model, text, params, duration_s, rtf, mtime, size_bytes } ]',
  },
  {
    method: 'POST',
    path: '/api/prepare',
    title: 'تحضير النص (وكيل)',
    desc: 'يحوّل الأرقام والتواريخ والاختصارات إلى كلمات منطوقة، ويضيف التشكيل اختيارياً. يعمل على النص فقط.',
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
    title: 'التأليف التلقائي (وكيل)',
    desc: 'يكتب نصاً عربياً للمهمة المطلوبة ويضبط إعدادات النموذجين. يتطلب OPENAI_API_KEY على الخادم.',
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
    title: 'تنزيل ملف صوتي',
    desc: 'يخدم أي ملف يظهر في السجل أو في ردّ التوليد/التفريغ. رابط مباشر — لا حاجة لتجربته من هنا.',
    fields: [
      { name: 'model',    type: 'select', in: 'path', options: ['omnivoice_ft', 'omnivoice_base', 'transcribe'], value: 'omnivoice_ft' },
      { name: 'filename', type: 'text',   in: 'path', value: 'omnivoice_xxxxxxxxxxxx.wav' },
    ],
    noTry: true,
  },
];

const $ = id => document.getElementById(id);
const escapeHtml = v => String(v ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const fieldsIn = (spec, where) => spec.fields.filter(f => (f.in || 'body') === where);
const slug = spec => `${spec.method}-${spec.path}`.replace(/[^a-z0-9]+/gi, '-').toLowerCase();

// ── Request building ──────────────────────────────────────────
// Reads the rendered form back out; used by both the live call and the curl snippet.
function readValues(spec, form) {
  const out = {};
  for (const f of spec.fields) {
    const el = form ? form.querySelector(`[name="${f.name}"]`) : null;
    out[f.name] = f.type === 'file' ? (el && el.files[0]) || null
                                    : (el ? el.value : (f.value ?? ''));
  }
  return out;
}

function buildUrl(spec, values) {
  let path = spec.path.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(values[k] ?? ''));
  const query = fieldsIn(spec, 'query')
    .filter(f => String(values[f.name] ?? '').trim())
    .map(f => `${f.name}=${encodeURIComponent(values[f.name])}`);
  return query.length ? `${path}?${query.join('&')}` : path;
}

// Body fields, minus the ones the user left empty (the server applies its own defaults).
function bodyEntries(spec, values) {
  return fieldsIn(spec, 'body').filter(f => {
    const v = values[f.name];
    return f.type === 'file' ? v instanceof File : String(v ?? '').trim() !== '';
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
      <button type="button" class="api-mic" hidden>🎙 سجّل</button>
      <span class="api-mic-state"></span>
    </span>`;
  if (f.type === 'select') return `<select name="${f.name}">${f.options.map(o =>
    `<option value="${escapeHtml(o)}" ${o === f.value ? 'selected' : ''}>${escapeHtml(o || '(فارغ)')}</option>`
  ).join('')}</select>`;
  return `<input type="text" name="${f.name}" value="${escapeHtml(f.value ?? '')}" dir="auto">`;
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
          <span>النموذج</span>
          <a href="${escapeHtml(spec.model.url)}" target="_blank" rel="noopener noreferrer"
             dir="ltr">${escapeHtml(spec.model.name)}</a>
          ${spec.model.note ? `<small>${escapeHtml(spec.model.note)}</small>` : ''}
        </div>` : ''}
      ${spec.returns ? `<div class="api-returns"><span>يعيد</span><code>${escapeHtml(spec.returns)}</code></div>` : ''}
      <form class="api-form" data-id="${id}">
        ${spec.fields.map(fieldRowHtml).join('')}
        ${spec.noTry ? '' : `<button type="submit" class="btn-prep api-run">▷ جرّب الآن</button>`}
      </form>
      <div class="api-curl">
        <div class="api-curl-head">
          <span>curl</span>
          <button type="button" class="btn-ghost btn-xs api-copy">نسخ</button>
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
    (f.type === 'file' ? !(values[f.name] instanceof File) : !String(values[f.name] ?? '').trim()));
  if (missing) {
    showResponse(card, 0, `الحقل المطلوب "${missing.name}" فارغ`, 0);
    return;
  }

  btn.disabled = true;
  btn.textContent = '… جاري التنفيذ';
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
    btn.textContent = '▷ جرّب الآن';
  }
}

function showResponse(card, status, text, ms, parsed = null) {
  const box = card.querySelector('.api-response');
  box.hidden = false;
  const ok = status >= 200 && status < 300;
  const statusEl = box.querySelector('.api-status');
  statusEl.textContent = status ? `HTTP ${status}` : 'فشل الطلب';
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
    btn.textContent = '🎙 سجّل';
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
    btn.textContent = '⏹ إيقاف';
    btn.classList.add('recording');
    timer = setInterval(() => {
      state.textContent = `● ${MicRecorder.fmtElapsed(Date.now() - handle.startedAt)}`;
    }, 250);
  });
}

// ── Init ──────────────────────────────────────────────────────
function init() {
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
      e.currentTarget.textContent = 'تم النسخ ✓';
      setTimeout(() => { e.currentTarget.textContent = 'نسخ'; }, 1500);
    });
  }
}

document.addEventListener('DOMContentLoaded', init);
