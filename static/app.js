'use strict';

// ── Model definitions ────────────────────────────────────────
const MODELS = {
  omnivoice: {
    id: 'omnivoice',
    name: 'OmniVoice',
    icon: '🌐',
    specs: '0.6B · 24kHz · 600+ lang',
    role: 'أوسع تغطية لغات (600+) وجيد للعربية؛ لكن وصف الصوت (instruct) مُدرَّب على الإنجليزية/الصينية فقط.',
    traits: ['600+ لغة', 'Arabic-ready', 'Voice design', '24kHz'],
    profile: [
      { label: 'أفضل استخدام', value: 'كخط أساس للنطق العربي أو نقل صوت مرجعي بين اللغات.' },
      { label: 'التحكم', value: 'اللهجة تُختار عبر لغة النموذج العربية تلقائياً؛ الجنس/العمر/الأسلوب عبر instruct الإنجليزي + صوت مرجعي اختياري.' },
      { label: 'الأداء محلياً', value: 'عادةً أسرع من VoxCPM2 على CPU في هذا السيرفر.' },
    ],
    compareNote: 'استخدمه كخط أساس للنطق والتغطية اللغوية.',
    params: [
      { id: 'voice', label: 'صوت جاهز (مستنسخ)', type: 'select', default: '',
        options: [
          { value: '',      label: 'بدون — صوت النموذج' },
          { value: 'abeer', label: 'عبير — سعودية' },
        ],
        hint: 'أصوات مرجعية مضمّنة في السيرفر تُستنسخ تلقائياً (voices/). رفع صوت مرجعي يدوياً من لوحة الاستنساخ يتجاوز هذا الاختيار.' },
      { id: 'speaker', label: 'Voice / Style Prompt', type: 'text',
        placeholder: 'e.g. female, young adult, whisper', default: '',
        hint: 'وصف الصوت بمفردات OmniVoice الإنجليزية فقط: الجنس (male/female)، العمر (young adult/middle-aged/elderly)، النبرة (low/high pitch)، الأسلوب (whisper). لا يقبل وصفاً عربياً حراً. اللهجة العربية تُضبط تلقائياً عبر لغة النموذج، وليست جزءاً من هذا الوصف. اتركه فارغاً للصوت الافتراضي.' },
    ],
    emotionTags: ['[laughter]'],   // base model only documents [laughter]; [applause] is unsupported
    cloneFields: ['ref_audio', 'ref_text'],
    formFields: { ref_audio: 'ref_audio', ref_text: 'ref_text' },
  },
  voxcpm2: {
    id: 'voxcpm2',
    name: 'VoxCPM2',
    icon: '🔊',
    specs: '2B · 48kHz · Diffusion',
    role: 'جودة إخراج أعلى واستنساخ صوت مرن (30 لغة)؛ العربية مدعومة لكن بدقة أقل (WER ~13%)، وأثقل نموذج على CPU.',
    traits: ['30 لغة', '48kHz', 'Voice design', 'Cloning'],
    profile: [
      { label: 'أفضل استخدام', value: 'المقاطع النهائية عالية الجودة أو اختبار تصميم/استنساخ صوت متقدم.' },
      { label: 'التحكم', value: 'CFG + timesteps + صوت مرجعي. اللهجة تُحقن كبادئة (Arabic) قبل النص؛ المرجع يثبّتها أكثر.' },
      { label: 'الأداء محلياً', value: 'الأبطأ على CPU؛ استخدم 5 timesteps للمسودات و20 للجودة.' },
    ],
    compareNote: 'قارنه عندما تكون الجودة أهم من زمن التوليد.',
    params: [
      { id: 'style',               label: 'Style cue',        type: 'text',
        placeholder: 'مثال: calm, formal أو cheerful, energetic', default: '',
        hint: 'وصف أسلوب/نبرة حر يُحقن كبادئة بين قوسين قبل النص. يضبطه وكيل التأليف تلقائياً؛ اتركه فارغاً للأسلوب الافتراضي.' },
      { id: 'cfg_value',           label: 'CFG Value',        type: 'range',  min: 1.0, max: 5.0, step: 0.1, default: 2.0,
        hint: 'أعلى = اتباع أقوى للوصف أو المرجع، وقد يزيد الحدة أو الاصطناع.' },
      { id: 'inference_timesteps', label: 'Timesteps',        type: 'select', options: [5, 10, 20], default: 10,
        hint: '5 أسرع للمسودات، 10 متوازن، 20 أفضل جودة لكنه أبطأ.' },
    ],
    emotionTags: ['(calm)', '(excited)', '(sad)', '(whisper)', '(cheerful)'],
    cloneFields: ['ref_wav', 'prompt_wav', 'prompt_text'],
    formFields: {
      reference_wav: 'ref_wav',
      prompt_wav:    'prompt_wav',
      prompt_text:   'prompt_text',
    },
    cloneHint: 'تلميح: أضف وصفاً في أقواس أمام النص: (calm and slow) النص هنا',
  },
};

// ── Arabic dialects ───────────────────────────────────────────
// Language is locked to Arabic for every model; this picks the dialect that each
// worker injects via its native lever (OmniVoice instruct, VoxCPM2 prefix).
const DIALECTS = [
  { id: 'msa',      label: 'الفصحى' },
  { id: 'saudi',    label: 'سعودي' },
  { id: 'egyptian', label: 'مصري' },
];
const dialectLabel = id => (DIALECTS.find(d => d.id === id) || DIALECTS[0]).label;

// Optional voice persona (empty id = let the model decide), injected alongside the dialect.
const GENDERS = [
  { id: '',       label: 'تلقائي' },
  { id: 'male',   label: 'ذكر' },
  { id: 'female', label: 'أنثى' },
];
const AGES = [
  { id: '',       label: 'تلقائي' },
  { id: 'young',  label: 'شاب' },
  { id: 'middle', label: 'متوسط' },
  { id: 'old',    label: 'كبير السن' },
];
const attrLabel = (list, id) => (list.find(o => o.id === id) || list[0]).label;

// English descriptors for VoxCPM2's leading-parenthetical cue — MUST match its worker map.
const DIALECT_EN = {
  msa: 'Modern Standard Arabic', saudi: 'Saudi (Najdi) Arabic', egyptian: 'Egyptian Arabic',
};
// OmniVoice picks the dialect via its native ISO 639-3 language code — MUST match the worker map.
const DIALECT_LANG = {
  msa: 'arb', saudi: 'ars', egyptian: 'arz',
};
const GENDER_EN = { male: 'male', female: 'female' };
const AGE_EN = { young: 'young adult', middle: 'middle-aged', old: 'elderly' };

// Auto-compose agent: job presets (ids MUST match compose.py JOBS).
const JOBS = [
  { id: 'customer_service', label: 'خدمة العملاء' },
  { id: 'booking',          label: 'وكيل حجوزات' },
  { id: 'storytelling',     label: 'سرد قصة' },
  { id: 'announcement',     label: 'إعلان' },
];

// Reproduces each worker's injection so the user sees the exact string that reaches the model.
// Returns { text, instruct?, lang? } — `instruct`/`lang` are only present for OmniVoice.
function buildModelInput(mid, text) {
  const v = paramValues[mid] || {};
  const desc = DIALECT_EN[v.dialect || 'msa'] || DIALECT_EN.msa;
  const persona = [GENDER_EN[v.gender] || '', AGE_EN[v.age] || ''].filter(Boolean).join(' ');
  const body = text || '';

  if (mid === 'voxcpm2') {
    const style = (v.style || '').trim();
    const cue = [style, persona, desc].filter(Boolean).join(', ');
    return { text: `(${cue}) ${body}` };
  }
  if (mid === 'omnivoice') {
    // Dialect → language code (not instruct); instruct carries only valid EN voice-design tokens.
    const attrs = [];
    const sp = (v.speaker || '').trim();
    if (sp) attrs.push(sp);
    if (GENDER_EN[v.gender]) attrs.push(GENDER_EN[v.gender]);
    if (AGE_EN[v.age]) attrs.push(AGE_EN[v.age]);
    return { text: body, instruct: attrs.join(', '), lang: DIALECT_LANG[v.dialect || 'msa'] || DIALECT_LANG.msa };
  }
  return { text: body };
}

const SAMPLE_SENTENCES = [
  'مرحباً، كيف حالك؟',
  'أهلاً وسهلاً، يسعدنا تواجدكم معنا.',
  'أعلنت وزارة الصحة عن إطلاق حملة تطعيم وطنية شاملة.',
  'الذكاء الاصطناعي يُحدث ثورة في تحويل النص إلى كلام text-to-speech.',
  'اللغة العربية لغة سامية غنية بمفرداتها وتراثها الأدبي.',
];

// ── State ─────────────────────────────────────────────────────
let selectedModel = 'omnivoice';
let workerStatus  = { omnivoice: 'offline', voxcpm2: 'offline' };
let loadingModels = new Set();   // models with an in-flight /load request
let currentAudioUrl = null;
let isGenerating  = false;
let isComparing   = false;
let audioCtx      = null;
let paramValues   = {};  // { omnivoice: {speaker: '', ...}, ... }
let manualOverride = {}; // { omnivoice: {enabled, text, instruct}, ... } — verbatim model-input edits
let cloneFiles    = {};  // { ref_audio: File|null, ref_text: '', ... }
let compareSelection = {};
let currentCompareRunId = null;  // id of the comparison run currently being generated (for retry)
let expandedCompareRuns = new Set();  // ids of saved comparison runs expanded inline

// ── DOM helpers ───────────────────────────────────────────────
const $  = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

const escapeAttr = escapeHtml;  // escapeHtml is defined below (hoisted)

function formatTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function numeric(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatSeconds(value) {
  const n = numeric(value);
  return n === null || n <= 0 ? '—' : `${n.toFixed(2)}s`;
}

function formatRtf(value) {
  const n = numeric(value);
  return n === null || n <= 0 ? '—' : n.toFixed(2);
}

function formatSampleRate(value) {
  const n = numeric(value);
  if (n === null || n <= 0) return '—';
  if (n >= 1000) {
    const khz = n / 1000;
    return `${Number.isInteger(khz) ? khz.toFixed(0) : khz.toFixed(1)}kHz`;
  }
  return `${n}Hz`;
}

function rtfProfile(value) {
  const n = numeric(value);
  if (n === null || n <= 0) return { tone: 'neutral', label: 'غير معروف' };
  if (n <= 1) return { tone: 'fast', label: 'أسرع من الزمن الحقيقي' };
  if (n <= 5) return { tone: 'ok', label: 'مقبول للتجارب' };
  if (n <= 15) return { tone: 'slow', label: 'بطيء على CPU' };
  return { tone: 'very-slow', label: 'بطيء جداً على CPU' };
}

function metricGridHtml(meta) {
  const rtf = rtfProfile(meta.rtf);
  return `
    <div class="metric-grid">
      <div class="metric-cell">
        <span class="metric-label">زمن التوليد</span>
        <strong class="metric-value">${formatSeconds(meta.elapsed_s)}</strong>
      </div>
      <div class="metric-cell">
        <span class="metric-label">مدة الصوت</span>
        <strong class="metric-value">${formatSeconds(meta.duration_s)}</strong>
      </div>
      <div class="metric-cell">
        <span class="metric-label">RTF</span>
        <strong class="metric-value rtf-${rtf.tone}">${formatRtf(meta.rtf)}</strong>
        <small>${rtf.label}</small>
      </div>
      <div class="metric-cell">
        <span class="metric-label">العينة</span>
        <strong class="metric-value">${formatSampleRate(meta.sample_rate)}</strong>
      </div>
    </div>
  `;
}

function cloneLabel(key) {
  return {
    ref_audio: 'صوت مرجعي',
    ref_text: 'نص مرجعي',
    ref_wav: 'مرجع Basic',
    prompt_wav: 'صوت Prompt',
    prompt_text: 'نص Prompt',
  }[key] || key;
}

const selectOptionValue = o => (o && typeof o === 'object') ? o.value : o;

function optionSummary(mid, includeClone = true) {
  const model = MODELS[mid];
  const vals = paramValues[mid] || {};
  const entries = (model.params || []).map(p => {
    const raw = Object.prototype.hasOwnProperty.call(vals, p.id) ? vals[p.id] : p.default;
    let value = typeof raw === 'string' && !raw.trim() ? 'افتراضي' : raw;
    if (p.type === 'select') {
      const match = (p.options || []).find(o => selectOptionValue(o) == raw);
      if (match && typeof match === 'object') value = match.label;
    }
    return { label: p.label, value };
  });

  // Forced language + chosen dialect/persona lead the summary.
  const lead = [{ label: 'اللهجة', value: `العربية · ${dialectLabel(vals.dialect || 'msa')}` }];
  if (vals.gender) lead.push({ label: 'الجنس', value: attrLabel(GENDERS, vals.gender) });
  if (vals.age)    lead.push({ label: 'العمر', value: attrLabel(AGES, vals.age) });
  entries.unshift(...lead);

  if (includeClone) {
    const usedClone = [];
    for (const stateKey of Object.values(model.formFields || {})) {
      const val = cloneFiles[stateKey];
      if (val instanceof File) usedClone.push({ label: cloneLabel(stateKey), value: val.name });
      else if (typeof val === 'string' && val.trim()) usedClone.push({ label: cloneLabel(stateKey), value: 'موجود' });
    }
    entries.push(...usedClone);
    if (!usedClone.length && model.formFields) entries.push({ label: 'استنساخ', value: 'بدون مرجع' });
  }

  return entries;
}

function optionChipsHtml(entries) {
  if (!entries || !entries.length) return '';
  return `
    <div class="option-chips">
      ${entries.map(e => `
        <span class="option-chip">
          <b>${escapeHtml(e.label)}</b>
          <span>${escapeHtml(e.value)}</span>
        </span>
      `).join('')}
    </div>
  `;
}

function showToast(msg, type = '', duration = 3000) {
  const el = $('toast');
  el.textContent = msg;
  el.className = `toast ${type}`;
  void el.offsetHeight;
  el.classList.remove('hidden');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add('hidden'), duration);
}

// ── Init param values ─────────────────────────────────────────
function initParamValues() {
  for (const [mid, m] of Object.entries(MODELS)) {
    paramValues[mid] = { dialect: 'msa', gender: '', age: '' };   // Arabic forced; persona auto
    for (const p of m.params) {
      paramValues[mid][p.id] = p.default;
    }
  }
}

// ── Render model cards ────────────────────────────────────────
function renderModelCards() {
  const container = $('model-cards');
  container.innerHTML = '';
  for (const m of Object.values(MODELS)) {
    const st = workerStatus[m.id] || 'offline';
    // 'loading' = worker is up but the model isn't in RAM yet (loads on demand).
    const isLoading = loadingModels.has(m.id);
    const statusText = st === 'online'  ? '● متاح'
                     : st === 'offline' ? '● غير متاح'
                     : isLoading        ? '● جاري التحميل…'
                                        : '● غير محمّل';
    const statusCls = (st === 'loading') ? 'loading' : st;  // keep the blink while up-but-not-loaded
    const card = document.createElement('div');
    card.className = `model-card ${m.id} ${selectedModel === m.id ? 'active' : ''} ${st === 'offline' ? 'offline' : ''}`;
    card.dataset.model = m.id;
    card.innerHTML = `
      <div class="mc-header">
        <div class="mc-icon">${m.icon}</div>
        <div class="mc-main">
          <div class="mc-name">${escapeHtml(m.name)}</div>
          <div class="mc-specs">${escapeHtml(m.specs)}</div>
        </div>
      </div>
      <div class="mc-role">${escapeHtml(m.role)}</div>
      <div class="mc-traits">
        ${(m.traits || []).map(t => `<span>${escapeHtml(t)}</span>`).join('')}
      </div>
      <div class="mc-footer">
        <span class="mc-status ${statusCls}">${statusText}</span>
        ${st === 'loading'
          ? `<button class="mc-load-btn" data-load="${m.id}" ${isLoading ? 'disabled' : ''}>${isLoading ? 'جاري التحميل…' : 'تحميل النموذج'}</button>`
          : ''}
      </div>
    `;
    card.addEventListener('click', () => selectModel(m.id));
    const loadBtn = card.querySelector('.mc-load-btn');
    if (loadBtn) loadBtn.addEventListener('click', (e) => { e.stopPropagation(); loadModel(m.id); });
    container.appendChild(card);
  }
}

// ── Explicitly load (warm) a model into memory ────────────────
// Models load lazily on first synth; this lets the user trigger it ahead of time.
// On this CPU-only host a load takes ~2–3 min and ~6–7 GB RAM per model.
async function loadModel(id) {
  if (loadingModels.has(id) || workerStatus[id] === 'online') return;
  loadingModels.add(id);
  renderModelCards();
  const name = (MODELS[id] && MODELS[id].name) || id;
  showToast(`جاري تحميل ${name}… (قد يستغرق 2–3 دقائق)`, '', 4000);
  try {
    const r = await fetch(`/api/${id}/load`, { method: 'POST' });
    if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
    loadingModels.delete(id);
    await pollStatus();                 // refresh badges immediately
    showToast(`✓ تم تحميل ${name}`, 'success');
  } catch (e) {
    loadingModels.delete(id);
    renderModelCards();
    showToast(`تعذّر تحميل النموذج: ${String(e.message).slice(0, 160)}`, 'warn');
  }
}

// ── Render status badges ──────────────────────────────────────
function renderStatusBadges() {
  const row = $('status-row');
  row.innerHTML = '';
  for (const m of Object.values(MODELS)) {
    const st = workerStatus[m.id] || 'offline';
    const badge = document.createElement('div');
    badge.className = `status-badge ${st}`;
    badge.innerHTML = `<span class="status-dot"></span>${m.name}`;
    row.appendChild(badge);
  }
}

// ── Render params panel ───────────────────────────────────────
function renderModelInsights(model) {
  const rows = (model.profile || []).map(item => `
    <div class="insight-item">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
    </div>
  `).join('');

  return `
    <div class="model-insights ${model.id}">
      <div class="insight-head">
        <span class="insight-icon">${model.icon}</span>
        <div>
          <strong>${escapeHtml(model.name)}</strong>
          <p>${escapeHtml(model.role)}</p>
        </div>
      </div>
      <div class="insight-grid">${rows}</div>
      <div class="insight-note">${escapeHtml(model.compareNote)}</div>
    </div>
  `;
}

// Labeled dropdown bound to paramValues[selectedModel][key]; auto-sent with each request.
function makeAttrSelect(labelText, key, list) {
  const cur = paramValues[selectedModel][key] || '';
  const opts = list.map(o =>
    `<option value="${o.id}" ${o.id === cur ? 'selected' : ''}>${escapeHtml(o.label)}</option>`).join('');
  const cell = document.createElement('div');
  cell.style.cssText = 'display:flex;align-items:center;gap:6px';
  cell.innerHTML = `
    <label class="param-label" for="p-${key}" style="padding:0">${escapeHtml(labelText)}</label>
    <select class="param-select" id="p-${key}" style="min-width:100px">${opts}</select>
  `;
  cell.querySelector('select').addEventListener('change', e => {
    paramValues[selectedModel][key] = e.target.value;
    updateModelInputPreview();
  });
  return cell;
}

// Locked "Arabic" indicator + dialect / gender / age controls, shown for every model.
function renderLanguageBar(body) {
  const wrap = document.createElement('div');
  wrap.className = 'lang-dialect-row';
  wrap.style.cssText = 'display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px';

  const lock = document.createElement('span');
  lock.title = 'اللغة مثبّتة على العربية';
  lock.style.cssText = 'display:inline-flex;align-items:center;gap:4px;font-size:.72rem;font-weight:600;color:var(--txt2);background:#21262d;border:1px solid #30363d;border-radius:6px;padding:4px 8px';
  lock.textContent = '🔒 العربية';
  wrap.appendChild(lock);

  wrap.appendChild(makeAttrSelect('اللهجة', 'dialect', DIALECTS));
  wrap.appendChild(makeAttrSelect('الجنس',  'gender',  GENDERS));
  wrap.appendChild(makeAttrSelect('العمر',  'age',     AGES));
  body.appendChild(wrap);

  const hint = document.createElement('div');
  hint.className = 'param-hint';
  hint.style.marginBottom = '8px';
  hint.textContent = 'العربية مفروضة على كل النماذج؛ اختر اللهجة والجنس والعمر وتُحقن تلقائياً في كل طلب.';
  body.appendChild(hint);

  const preview = document.createElement('div');
  preview.id = 'model-input-preview';
  preview.style.cssText = 'margin:0 0 12px;padding:8px 10px;background:#161b22;border:1px solid #30363d;border-radius:8px';
  body.appendChild(preview);
  updateModelInputPreview();
}

// One labelled monospace block — shared by the live preview and the post-synth echo.
function codeLineHtml(label, value) {
  return `
    <div style="display:flex;flex-direction:column;gap:2px;margin-top:6px">
      <span style="font-size:.66rem;color:var(--txt2);font-weight:700">${escapeHtml(label)}</span>
      <code dir="auto" style="display:block;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:6px 8px;font-size:.74rem;line-height:1.55;color:#e6edf3;white-space:pre-wrap;word-break:break-word">${escapeHtml(value && value.trim() ? value : '—')}</code>
    </div>`;
}

function overrideState(mid) {
  if (!manualOverride[mid]) manualOverride[mid] = { enabled: false, text: '', instruct: '' };
  return manualOverride[mid];
}

// Editable counterpart of codeLineHtml — value is wired up after innerHTML is set.
function editLineHtml(label, id) {
  return `
    <div style="display:flex;flex-direction:column;gap:2px;margin-top:6px">
      <span style="font-size:.66rem;color:#d29922;font-weight:700">✏️ ${escapeHtml(label)}</span>
      <textarea id="${id}" dir="auto" rows="2" spellcheck="false"
        style="background:#0d1117;border:1px solid #d29922;border-radius:6px;padding:6px 8px;font-size:.74rem;line-height:1.55;color:#e6edf3;font-family:inherit;resize:vertical;width:100%"></textarea>
    </div>`;
}

// Live preview of the exact text/instruct that will actually be fed to the selected model.
// Mirrors buildModelInput() (which mirrors the worker injection), so it equals what's sent.
// "تعديل يدوي" turns the blocks into textareas whose content is sent verbatim instead.
function updateModelInputPreview() {
  const el = $('model-input-preview');
  if (!el) return;
  const ta = $('text-input');
  const mi = buildModelInput(selectedModel, ta ? ta.value.trim() : '');
  const ov = overrideState(selectedModel);

  let html = `
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
      <span style="font-size:.7rem;color:var(--txt2);font-weight:700">📤 الإدخال الفعلي المُرسَل إلى النموذج</span>
      <button type="button" id="btn-input-override" class="tag-chip" style="flex-shrink:0">
        ${ov.enabled ? '↺ رجوع للتلقائي' : '✏️ تعديل يدوي'}
      </button>
    </div>`;

  if (!ov.enabled) {
    if (mi.instruct !== undefined) {
      const v = paramValues[selectedModel] || {};
      html += codeLineHtml('لغة النموذج (language)', `${mi.lang} · العربية (${dialectLabel(v.dialect || 'msa')})`);
      html += codeLineHtml('وصف الصوت (instruct)', mi.instruct);
      html += codeLineHtml('النص (text)', mi.text);
    } else {
      html += codeLineHtml('النص المُرسَل (text)', mi.text);
    }
    el.innerHTML = html;
  } else {
    if (mi.instruct !== undefined) html += editLineHtml('وصف الصوت (instruct)', 'ov-instruct');
    html += editLineHtml('النص (text)', 'ov-text');
    const langNote = mi.lang
      ? 'يُرسَل المحتوى أعلاه حرفياً (بدون حقن الجنس/العمر)؛ لهجة اللغة العربية تبقى مُطبَّقة عبر لغة النموذج.'
      : 'يُرسَل المحتوى أعلاه إلى النموذج حرفياً (بدون حقن اللهجة/الجنس/العمر).';
    html += `<div class="param-hint" style="margin-top:6px">وضع التعديل اليدوي: ${escapeHtml(langNote)} اترك الحقل فارغاً للرجوع إلى القيمة التلقائية.</div>`;
    el.innerHTML = html;
    const t = $('ov-text');
    if (t) { t.value = ov.text; t.addEventListener('input', e => { ov.text = e.target.value; }); }
    const ins = $('ov-instruct');
    if (ins) { ins.value = ov.instruct; ins.addEventListener('input', e => { ov.instruct = e.target.value; }); }
  }

  $('btn-input-override').addEventListener('click', () => {
    ov.enabled = !ov.enabled;
    if (ov.enabled) {           // seed the editor with the current auto-built input
      ov.text = mi.text;
      ov.instruct = mi.instruct || '';
    }
    updateModelInputPreview();
  });
}

// Authoritative input echoed back by the worker for a generated clip (ground truth).
function sentInputHtml(meta) {
  if (!meta || (!meta.model_input && !meta.model_instruct)) return '';
  return `
    <div style="margin-top:10px;padding:8px 10px;background:#161b22;border:1px solid #30363d;border-radius:8px">
      <div style="font-size:.7rem;color:var(--txt2);font-weight:700">📤 ما أُرسل فعلياً إلى النموذج</div>
      ${meta.model_instruct ? codeLineHtml('وصف الصوت (instruct)', meta.model_instruct) : ''}
      ${codeLineHtml('النص (text)', meta.model_input)}
    </div>`;
}

function renderParams() {
  const body = $('params-body');
  const model = MODELS[selectedModel];
  body.innerHTML = renderModelInsights(model);
  renderLanguageBar(body);

  if (!model.params.length) {
    body.insertAdjacentHTML('beforeend', '<p class="param-empty">لا توجد معاملات إضافية.</p>');
    return;
  }

  for (const p of model.params) {
    const val = paramValues[selectedModel][p.id];
    const row = document.createElement('div');

    if (p.type === 'range') {
      row.className = 'param-row';
      row.innerHTML = `
        <label class="param-label" for="p-${p.id}">${p.label}</label>
        <span class="param-value" id="v-${p.id}">${val}</span>
        <input class="param-range ${selectedModel}-range" type="range"
          id="p-${p.id}" min="${p.min}" max="${p.max}" step="${p.step}" value="${val}">
        ${p.hint ? `<div class="param-hint">${escapeHtml(p.hint)}</div>` : ''}
      `;
      body.appendChild(row);
      row.querySelector('input').addEventListener('input', e => {
        const v = parseFloat(e.target.value);
        paramValues[selectedModel][p.id] = v;
        $(`v-${p.id}`).textContent = v;
      });

    } else if (p.type === 'select') {
      row.className = 'param-row';
      // Options are either primitives (numeric params) or {value, label} objects (string params).
      const numeric = typeof selectOptionValue(p.options[0]) === 'number';
      const opts = p.options.map(o => {
        const ov = selectOptionValue(o);
        const ol = (o && typeof o === 'object') ? o.label : o;
        return `<option value="${escapeHtml(String(ov))}" ${ov == val ? 'selected' : ''}>${escapeHtml(String(ol))}</option>`;
      }).join('');
      row.innerHTML = `
        <label class="param-label" for="p-${p.id}">${p.label}</label>
        <select class="param-select" id="p-${p.id}">${opts}</select>
        ${p.hint ? `<div class="param-hint">${escapeHtml(p.hint)}</div>` : ''}
      `;
      body.appendChild(row);
      row.querySelector('select').addEventListener('change', e => {
        paramValues[selectedModel][p.id] = numeric ? parseInt(e.target.value) : e.target.value;
      });

    } else if (p.type === 'text') {
      const wrap = document.createElement('div');
      wrap.style.display = 'flex';
      wrap.style.flexDirection = 'column';
      wrap.style.gap = '4px';
      wrap.innerHTML = `
        <label class="param-label" style="padding-bottom:0" for="p-${p.id}">${p.label}</label>
        <input class="param-text" type="text" id="p-${p.id}"
          placeholder="${escapeHtml(p.placeholder || '')}" value="${escapeHtml(val)}">
        ${p.hint ? `<div class="param-hint">${escapeHtml(p.hint)}</div>` : ''}
      `;
      body.appendChild(wrap);
      wrap.querySelector('input').addEventListener('input', e => {
        paramValues[selectedModel][p.id] = e.target.value;
        updateModelInputPreview();   // OmniVoice style prompt feeds the instruct preview
      });
    }
  }
}

// ── Render emotion tags ───────────────────────────────────────
function renderTags() {
  const strip = $('tag-strip');
  const model = MODELS[selectedModel];
  if (!model.emotionTags || !model.emotionTags.length) {
    strip.className = 'tag-strip empty';
    return;
  }
  strip.className = 'tag-strip';
  strip.innerHTML = '';
  for (const tag of model.emotionTags) {
    const btn = document.createElement('button');
    btn.className = 'tag-chip';
    btn.textContent = tag;
    btn.title = 'أضف إلى النص';
    btn.addEventListener('click', () => insertTag(tag));
    strip.appendChild(btn);
  }
}

function insertTag(tag) {
  const ta = $('text-input');
  const start = ta.selectionStart;
  const end   = ta.selectionEnd;
  const val   = ta.value;
  const before = val.slice(0, start);
  const after  = val.slice(end);
  ta.value = before + tag + ' ' + after;
  const newPos = start + tag.length + 1;
  ta.setSelectionRange(newPos, newPos);
  ta.focus();
  updateCharCount();
  updateModelInputPreview();
}

// ── Render voice-cloning panel ────────────────────────────────
function renderClonePanel() {
  const body = $('clone-body');
  const model = MODELS[selectedModel];
  body.innerHTML = '';

  if (model.cloneHint) {
    const hint = document.createElement('p');
    hint.style.cssText = 'font-size:.72rem;color:var(--txt2);margin-bottom:6px;direction:rtl;line-height:1.5';
    hint.textContent = model.cloneHint;
    body.appendChild(hint);
  }

  if (model.id === 'omnivoice') {
    body.appendChild(makeFileZone('ref_audio', 'الصوت المرجعي (WAV 5–30 ثانية)', 'audio/wav,audio/*'));
    body.appendChild(makeTextRow('ref_text', 'نص الصوت المرجعي (اختياري)', 'النص المنطوق في الصوت المرجعي…'));
  }

  if (model.id === 'voxcpm2') {
    body.appendChild(makeFileZone('ref_wav',    'الصوت المرجعي (Basic cloning)', 'audio/wav,audio/*'));
    body.appendChild(makeFileZone('prompt_wav', 'صوت البروميبت (Ultimate cloning)', 'audio/wav,audio/*'));
    body.appendChild(makeTextRow('prompt_text', 'نص البروميبت (Ultimate)', 'النص المنطوق في صوت البروميبت…'));
  }
}

function makeFileZone(key, label, accept) {
  const wrap = document.createElement('div');
  wrap.className = 'clone-row';
  wrap.innerHTML = `<div class="clone-row-label">${label}</div>`;

  const zone = document.createElement('div');
  zone.className = 'file-zone';
  zone.dataset.key = key;
  zone.innerHTML = `<span class="zone-label">اسحب ملف WAV هنا أو اضغط للاختيار</span><input type="file" accept="${accept}">`;

  const input = zone.querySelector('input');
  input.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) {
      cloneFiles[key] = file;
      zone.classList.add('has-file');
      zone.querySelector('.zone-label').textContent = `✓ ${file.name}`;
    }
  });

  wrap.appendChild(zone);
  return wrap;
}

function makeTextRow(key, label, placeholder) {
  const wrap = document.createElement('div');
  wrap.className = 'clone-row';
  wrap.innerHTML = `
    <div class="clone-row-label">${label}</div>
    <textarea class="param-text" rows="2" placeholder="${placeholder}" style="resize:vertical" data-clone-key="${key}"></textarea>
  `;
  wrap.querySelector('textarea').addEventListener('input', e => {
    cloneFiles[key] = e.target.value;
  });
  return wrap;
}

// ── Render compare checkboxes ─────────────────────────────────
function renderCompareChecks() {
  const container = $('compare-checks');
  container.innerHTML = '';
  for (const m of Object.values(MODELS)) {
    const label = document.createElement('label');
    label.className = 'compare-check';
    const hasSaved = Object.prototype.hasOwnProperty.call(compareSelection, m.id);
    const selected = hasSaved ? compareSelection[m.id] : workerStatus[m.id] === 'online';
    const checked = selected && workerStatus[m.id] === 'online' ? 'checked' : '';
    const disabled = workerStatus[m.id] !== 'online' ? 'disabled' : '';
    label.innerHTML = `
      <input type="checkbox" value="${m.id}" ${checked} ${disabled}>
      <span class="compare-name">${m.icon} ${escapeHtml(m.name)}</span>
      <small>${escapeHtml(m.compareNote)}</small>
    `;
    label.querySelector('input').addEventListener('change', e => {
      compareSelection[m.id] = e.target.checked;
      updateCompareLabel();
    });
    container.appendChild(label);
  }
  updateCompareLabel();
}

// Reflect the number of selected models on the compare button
function updateCompareLabel() {
  if (isComparing) return;
  const n = $$('#compare-checks input:checked').length;
  const label = $('compare-label');
  if (label) label.textContent = n ? `قارن الآن (${n})` : 'اختر نماذج للمقارنة';
  $('btn-compare').disabled = n === 0;
}

// ── Render sample chips ───────────────────────────────────────
function renderSampleChips() {
  const container = $('sample-chips');
  container.innerHTML = '';
  for (const s of SAMPLE_SENTENCES) {
    const chip = document.createElement('button');
    chip.className = 'sample-chip';
    chip.textContent = s;
    chip.title = s;
    chip.addEventListener('click', () => {
      $('text-input').value = s;
      updateCharCount();
      updateSynthBtn();
      updateModelInputPreview();
    });
    container.appendChild(chip);
  }
}

// ── Auto-compose agent ────────────────────────────────────────
// Populate the agent's input selects (job + dialect/gender/age) from the shared lists.
function renderComposePanel() {
  const fill = (id, list) => {
    const sel = $(id);
    if (sel) sel.innerHTML = list.map(o => `<option value="${o.id}">${escapeHtml(o.label)}</option>`).join('');
  };
  fill('compose-job', JOBS);
  fill('compose-dialect', DIALECTS);
  fill('compose-gender', GENDERS);
  fill('compose-age', AGES);
}

function setComposeStatus(msg, type = '') {
  const el = $('compose-status');
  if (el) { el.textContent = msg || ''; el.className = `compose-status ${type}`; }
}

// Ask the agent to write one Arabic script and configure BOTH engines from the chosen inputs.
async function composeWithAI() {
  const btn = $('btn-compose-agent');
  if (btn.disabled) return;

  btn.disabled = true;
  $('compose-agent-label').textContent = '… جاري التأليف';
  setComposeStatus('يكتب الوكيل النص ويضبط إعدادات النموذجين…');
  try {
    const r = await fetch('/api/compose', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job:     $('compose-job').value,
        dialect: $('compose-dialect').value || 'msa',
        gender:  $('compose-gender').value || '',
        age:     $('compose-age').value || '',
        brief:   $('compose-brief').value.trim(),
      }),
    });
    if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
    const result = await r.json();
    applyComposed(result);
    setComposeStatus(result.notes ? `✓ ${result.notes}` : '✓ تم ضبط النموذجين', 'success');
    showToast('تم تأليف النص وضبط النموذجين ✓', 'success');
  } catch (e) {
    setComposeStatus(`خطأ: ${String(e.message).slice(0, 220)}`, 'error');
    showToast('تعذّر التأليف التلقائي', 'error', 5000);
  } finally {
    btn.disabled = false;
    $('compose-agent-label').textContent = '✨ أكمل بالذكاء الاصطناعي';
  }
}

// Write the agent result into BOTH models' controls + the shared script, then refresh the UI.
function applyComposed(result) {
  const dialect = DIALECTS.some(d => d.id === result.dialect) ? result.dialect : 'msa';
  const gender  = ['', 'male', 'female'].includes(result.gender) ? result.gender : '';
  const age     = ['', 'young', 'middle', 'old'].includes(result.age) ? result.age : '';

  // Shared, per-model voice settings — applied to every model so Compare uses tuned params.
  for (const mid of Object.keys(MODELS)) {
    const v = paramValues[mid];
    v.dialect = dialect; v.gender = gender; v.age = age;
    if (manualOverride[mid]) manualOverride[mid].enabled = false;
  }
  paramValues.omnivoice.speaker = result.omnivoice_instruct || '';
  paramValues.voxcpm2.style = result.voxcpm2_style || '';
  if (Number.isFinite(result.cfg_value)) paramValues.voxcpm2.cfg_value = result.cfg_value;
  if (Number.isFinite(result.inference_timesteps)) paramValues.voxcpm2.inference_timesteps = result.inference_timesteps;

  // One shared plain-Arabic script (each engine applies its own style mechanism).
  $('text-input').value = result.text || '';

  // Keep the compose-panel selects in sync with what the agent settled on.
  if ($('compose-dialect')) $('compose-dialect').value = dialect;
  if ($('compose-gender'))  $('compose-gender').value = gender;
  if ($('compose-age'))     $('compose-age').value = age;

  renderParams();          // re-render the current model's controls with the new values
  updateCharCount();
  updateSynthBtn();
  updateModelInputPreview();
}

// ── Text-Prep agent ───────────────────────────────────────────
// Rewrites the text BEFORE synthesis (numbers→words + optional tashkeel). The workers/models
// are never touched — only the `text` string changes. The agent's result is shown as a
// before/after preview; nothing reaches the text box until the user clicks «اعتمد».
let prepBackup = null;       // last pre-apply text, for one-step undo
let pendingPrepText = null;  // the prepared text awaiting the user's accept/discard

function setPrepStatus(msg, type = '') {
  const el = $('prep-status');
  if (el) { el.textContent = msg || ''; el.className = `compose-status ${type}`; }
}

function togglePrepOption(btn) {
  const on = btn.dataset.on !== '1';
  btn.dataset.on = on ? '1' : '0';
  btn.classList.toggle('active', on);
}

async function prepareText() {
  const btn  = $('btn-prep');
  if (btn.disabled) return;
  const text = $('text-input').value.trim();
  if (!text) { showToast('لا يوجد نص لتحضيره', 'error'); return; }

  const normalize  = $('prep-normalize').dataset.on === '1';
  const diacritize = $('prep-diacritize').dataset.on === '1';
  if (!normalize && !diacritize) {
    setPrepStatus('فعِّل «الأرقام→كلمات» أو «تشكيل» أولاً', 'error');
    return;
  }

  btn.disabled = true;
  $('prep-label').textContent = '… جاري التحضير';
  setPrepStatus('يحضّر الوكيل النص…');
  try {
    const r = await fetch('/api/prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        dialect: (paramValues[selectedModel] && paramValues[selectedModel].dialect) || 'msa',
        normalize, diacritize,
      }),
    });
    if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
    const result = await r.json();

    showPrepPreview(text, result);
    setPrepStatus(result.notes ? `✓ ${result.notes}` : '✓ جاهز — راجِع المقارنة ثم اعتمد', 'success');
  } catch (e) {
    setPrepStatus(`خطأ: ${String(e.message).slice(0, 220)}`, 'error');
    showToast('تعذّر تحضير النص', 'error', 5000);
  } finally {
    btn.disabled = false;
    $('prep-label').textContent = '✦ حضّر النص';
  }
}

// Render the before/after rows for whichever stages were produced; box stays untouched for now.
function showPrepPreview(original, result) {
  $('prep-text-original').textContent = original;

  const normRow = $('prep-row-normalized');
  if (result.normalized) { $('prep-text-normalized').textContent = result.normalized; normRow.hidden = false; }
  else normRow.hidden = true;

  const tashRow = $('prep-row-diacritized');
  if (result.diacritized) { $('prep-text-diacritized').textContent = result.diacritized; tashRow.hidden = false; }
  else tashRow.hidden = true;

  pendingPrepText = result.text || original;
  $('prep-preview').hidden = false;
}

// «اعتمد»: back up the current box (for ↶ undo), drop the prepared text in, hide the preview.
function applyPrep() {
  if (pendingPrepText === null) return;
  prepBackup = $('text-input').value;
  $('btn-prep-undo').hidden = false;
  $('text-input').value = pendingPrepText;
  hidePrepPreview();
  showToast('تم اعتماد النص ✓ — راجِعه ثم ولّد', 'success');
  updateCharCount();
  updateSynthBtn();
  updateModelInputPreview();
}

function cancelPrep() {
  hidePrepPreview();
  setPrepStatus('');
}

function hidePrepPreview() {
  pendingPrepText = null;
  $('prep-preview').hidden = true;
}

function undoPrep() {
  if (prepBackup === null) return;
  $('text-input').value = prepBackup;
  prepBackup = null;
  $('btn-prep-undo').hidden = true;
  setPrepStatus('');
  updateCharCount();
  updateSynthBtn();
  updateModelInputPreview();
}

// Drop the saved backup + hide the undo button (manual edit / clear supersedes the last apply).
function invalidatePrepUndo() {
  if (prepBackup === null) return;
  prepBackup = null;
  $('btn-prep-undo').hidden = true;
}

// ── Select model ──────────────────────────────────────────────
function selectModel(id) {
  selectedModel = id;
  cloneFiles = {};
  renderModelCards();
  renderParams();
  renderTags();
  renderClonePanel();
  renderCompareChecks();
  updateSynthBtn();

  // Update synth button color
  const btn = $('btn-synth');
  btn.className = `btn-synth ${id}`;
}

// ── Char counter ──────────────────────────────────────────────
function updateCharCount() {
  const len = $('text-input').value.length;
  const el  = $('char-count');
  el.textContent = len;
  el.className = `char-count ${len > 800 ? 'warn' : ''}`;
}

function updateSynthBtn() {
  const hasText = $('text-input').value.trim().length > 0;
  const online  = workerStatus[selectedModel] === 'online';
  $('btn-synth').disabled = !hasText || isGenerating;
  $('synth-label').textContent = !online ? 'النموذج غير متاح' :
    isGenerating ? 'جاري التوليد…' : 'توليد الصوت';
}

// ── Poll worker health ────────────────────────────────────────
async function pollStatus() {
  try {
    const r = await fetch('/api/status');
    if (!r.ok) return;
    const data = await r.json();
    for (const [mid, info] of Object.entries(data)) {
      if (!MODELS[mid]) continue;
      if (info.status === 'offline') {
        workerStatus[mid] = 'offline';
      } else if (info.model_loaded) {
        workerStatus[mid] = 'online';
      } else {
        workerStatus[mid] = 'loading';
      }
    }
  } catch { /* server not yet up */ }
  renderStatusBadges();
  renderModelCards();
  renderCompareChecks();
  updateSynthBtn();
}

// ── Current "instruct" (voice description / prompt text) ──────
// What counts as the instruction differs per model:
//   omnivoice → speaker voice description, voxcpm2 → prompt_text,
//   fish → emotion tags are inline in the text (no separate field).
function currentInstruct() {
  if (selectedModel === 'omnivoice') return (paramValues.omnivoice.speaker || '').trim();
  if (selectedModel === 'voxcpm2')   return (cloneFiles.prompt_text || '').trim();
  return '';
}

// ── Build FormData for synthesis ──────────────────────────────
// paramsOverride lets a retry rebuild the exact params captured at compare time.
function buildFormDataForModel(mid, text, includeClone = true, paramsOverride = null) {
  const fd = new FormData();
  fd.append('text', text);

  // Model-specific params
  const vals = paramsOverride || paramValues[mid] || {};
  for (const [k, v] of Object.entries(vals)) {
    fd.append(k, v);
  }

  // Manual override: the worker uses these verbatim and skips its own injection.
  const ov = manualOverride[mid];
  if (ov && ov.enabled) {
    fd.append('model_input_override', ov.text);
    if (mid === 'omnivoice') fd.append('model_instruct_override', ov.instruct);
  }

  // Clone files/text
  if (includeClone) {
    const model = MODELS[mid];
    for (const [formKey, stateKey] of Object.entries(model.formFields || {})) {
      const val = cloneFiles[stateKey];
      if (val instanceof File)   fd.append(formKey, val, val.name);
      else if (typeof val === 'string' && val.trim()) fd.append(formKey, val.trim());
    }
  }

  return fd;
}

function buildFormData() {
  return buildFormDataForModel(selectedModel, $('text-input').value.trim(), true);
}

// ── Synthesize ────────────────────────────────────────────────
async function synthesize() {
  if (isGenerating) return;
  const text = $('text-input').value.trim();
  if (!text) return;

  isGenerating = true;
  updateSynthBtn();
  $('synth-progress').classList.remove('hidden');
  $('progress-hint').textContent = 'جاري التوليد…';

  let hintTimer = null;
  if (workerStatus[selectedModel] === 'loading') {
    hintTimer = setTimeout(() => {
      $('progress-hint').textContent = 'جاري تحميل النموذج (قد يستغرق 1–2 دقيقة)…';
    }, 3000);
  }

  try {
    const fd = buildFormData();
    const r  = await fetch(`/api/${selectedModel}/synthesize`, { method: 'POST', body: fd });

    if (!r.ok) {
      const err = await r.text();
      throw new Error(err || `HTTP ${r.status}`);
    }

    const result = await r.json();
    const audioUrl = `/audio/${selectedModel}/${result.filename}`;
    const options = optionSummary(selectedModel, true);

    await loadPlayer(audioUrl, { ...result, options }, text);
    addToHistory({
      ...result, text, url: audioUrl, options, timestamp: Date.now(),
      instruct: currentInstruct(),
      params: { ...paramValues[selectedModel] },
    });
    showToast('تم توليد الصوت بنجاح ✓', 'success');

  } catch (e) {
    showToast(`خطأ: ${e.message}`, 'error', 6000);
  } finally {
    clearTimeout(hintTimer);
    isGenerating = false;
    $('synth-progress').classList.add('hidden');
    updateSynthBtn();
  }
}

// ── Audio player ──────────────────────────────────────────────
async function loadPlayer(url, meta, text) {
  currentAudioUrl = url;
  $('player-empty').classList.add('hidden');
  $('player-content').classList.remove('hidden');

  const audio = $('audio-el');
  audio.src = url;
  await audio.load();

  // Badges
  const badges = $('player-badges');
  const model = MODELS[meta.model] || { name: meta.model, role: '' };
  const rtf = rtfProfile(meta.rtf);
  badges.innerHTML = `
    <span class="model-badge ${meta.model}">${escapeHtml(model.name || meta.model)}</span>
    <span class="rtf-badge rtf-${rtf.tone}">${rtf.label}</span>
    <span class="rtf-badge">${formatSeconds(meta.elapsed_s)} توليد</span>
  `;

  const insights = $('player-insights');
  if (insights) {
    const options = meta.options || optionSummary(meta.model, false);
    insights.innerHTML = `
      <p class="player-model-note">${escapeHtml(model.role || '')}</p>
      ${metricGridHtml(meta)}
      ${optionChipsHtml(options)}
      ${sentInputHtml(meta)}
    `;
  }

  // Download
  const dl = $('btn-dl');
  dl.href = url;
  dl.download = meta.filename;

  // Player button color
  const playBtn = $('btn-play');
  playBtn.className = `btn-play ${meta.model === 'voxcpm2' ? 'vox' : meta.model}`;

  // Reset time
  $('cur-time').textContent = '0:00';
  $('tot-time').textContent = formatTime(meta.duration_s || 0);
  $('waveform-progress').style.width = '0%';

  // Draw waveform
  drawWaveform(url, meta.model);
}

// ── Waveform drawing ──────────────────────────────────────────
async function drawWaveform(url, mid = selectedModel) {
  const canvas = $('waveform');
  const ctx    = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
  canvas.height = 72 * (window.devicePixelRatio || 1);
  ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

  const W = canvas.offsetWidth;
  const H = 72;

  ctx.fillStyle = '#21262d';
  ctx.fillRect(0, 0, W, H);

  try {
    const resp  = await fetch(url);
    const buf   = await resp.arrayBuffer();
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const decoded = await audioCtx.decodeAudioData(buf);
    const data    = decoded.getChannelData(0);
    const step    = Math.ceil(data.length / W);
    const amp     = H / 2;

    // Compute normalized peaks
    const peaks = [];
    let globalMax = 0;
    for (let i = 0; i < W; i++) {
      let max = 0;
      for (let j = 0; j < step; j++) {
        const s = Math.abs(data[i * step + j] || 0);
        if (s > max) max = s;
      }
      peaks.push(max);
      if (max > globalMax) globalMax = max;
    }
    if (globalMax === 0) globalMax = 1;

    ctx.fillStyle = '#21262d';
    ctx.fillRect(0, 0, W, H);

    // Color based on model
    const color = mid === 'voxcpm2' ? '#3fb950' : '#58a6ff';
    ctx.fillStyle = color + '90';

    for (let i = 0; i < W; i++) {
      const normalized = peaks[i] / globalMax;
      const barH = normalized * amp * 0.9;
      ctx.fillRect(i, amp - barH, 1, barH * 2);
    }
  } catch {
    // Fallback: just show a flat line
    ctx.strokeStyle = '#30363d';
    ctx.beginPath();
    ctx.moveTo(0, 36);
    ctx.lineTo(W, 36);
    ctx.stroke();
  }
}

// ── Audio playback ────────────────────────────────────────────
function setupAudioEvents() {
  const audio   = $('audio-el');
  const playBtn = $('btn-play');

  playBtn.addEventListener('click', () => {
    if (audio.paused) {
      if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
      audio.play();
    } else {
      audio.pause();
    }
  });

  audio.addEventListener('play',  () => { playBtn.textContent = '⏸'; });
  audio.addEventListener('pause', () => { playBtn.textContent = '▶'; });
  audio.addEventListener('ended', () => { playBtn.textContent = '▶'; });

  audio.addEventListener('timeupdate', () => {
    $('cur-time').textContent = formatTime(audio.currentTime);
    if (audio.duration) {
      $('waveform-progress').style.width = (audio.currentTime / audio.duration * 100) + '%';
    }
  });

  audio.addEventListener('loadedmetadata', () => {
    $('tot-time').textContent = formatTime(audio.duration);
  });

  // Click waveform to seek
  $('waveform').addEventListener('click', e => {
    if (!audio.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    audio.currentTime = ratio * audio.duration;
  });
}

// ── History ───────────────────────────────────────────────────
const HISTORY_KEY = 'tts_history_v2';
const HISTORY_COLLAPSED_KEY = 'tts_history_collapsed_v1';
let historyItems = [];
let historyCollapsed = false;

function loadHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    historyItems = Array.isArray(saved) ? saved.filter(i => MODELS[i.model]) : [];
  } catch { historyItems = []; }
}

function loadHistoryCollapsed() {
  try {
    historyCollapsed = localStorage.getItem(HISTORY_COLLAPSED_KEY) === '1';
  } catch {
    historyCollapsed = false;
  }
  applyHistoryCollapsedState();
}

function saveHistory() {
  // Keep last 200 items
  const trimmed = historyItems.slice(0, 200);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
}

function setHistoryCollapsed(collapsed) {
  historyCollapsed = Boolean(collapsed);
  try {
    localStorage.setItem(HISTORY_COLLAPSED_KEY, historyCollapsed ? '1' : '0');
  } catch {}
  applyHistoryCollapsedState();
}

function applyHistoryCollapsedState() {
  const card = document.querySelector('.history-card');
  const list = $('history-list');
  const btn = $('btn-toggle-history');
  if (!card || !list || !btn) return;

  card.classList.toggle('history-collapsed', historyCollapsed);
  list.setAttribute('aria-hidden', String(historyCollapsed));
  btn.setAttribute('aria-expanded', String(!historyCollapsed));
  btn.textContent = historyCollapsed ? 'فتح' : 'طي';
  btn.title = historyCollapsed ? 'فتح السجل' : 'طي السجل';
}

function toggleHistoryCollapsed() {
  setHistoryCollapsed(!historyCollapsed);
}

function addToHistory(item) {
  historyItems.unshift(item);
  saveHistory();
  renderHistory();
}

function renderHistory(filterModel = 'all') {
  const list   = $('history-list');
  const empty  = $('history-empty');
  const filter = $('history-filter').value;
  const model  = filterModel === 'all' ? filter : filterModel;

  const items = model === 'all' ? historyItems : historyItems.filter(i => i.model === model);

  if (!items.length) {
    empty.classList.remove('hidden');
    list.querySelectorAll('.history-item').forEach(e => e.remove());
    return;
  }
  empty.classList.add('hidden');

  // Re-render
  list.querySelectorAll('.history-item').forEach(e => e.remove());
  for (const item of items) {
    const el = document.createElement('div');
    el.className = `history-item ${item.model}`;
    el.dataset.url = item.url;
    const textSnippet = (item.text || item.filename || '').slice(0, 50);
    const ago = formatAgo(item.timestamp);
    const instruct = (item.instruct || '').trim();
    const instructRow = instruct
      ? `<div class="hi-instruct" title="${escapeAttr(instruct)}">🎙 ${escapeHtml(instruct.slice(0, 50))}</div>`
      : '';
    const metaBits = [
      `${formatSeconds(item.elapsed_s)} توليد`,
      `${formatSeconds(item.duration_s)} صوت`,
      `RTF ${formatRtf(item.rtf)}`,
      ago,
    ].filter(v => v && !v.startsWith('—'));
    el.innerHTML = `
      <div class="hi-badge"><span class="model-badge ${item.model}">${(MODELS[item.model] && MODELS[item.model].icon) || ''}</span></div>
      <div class="hi-info">
        <div class="hi-filename">${escapeHtml(textSnippet)}</div>
        ${instructRow}
        <div class="hi-meta">${escapeHtml(metaBits.join(' · '))}</div>
      </div>
      <div class="hi-actions">
        <button class="hi-btn play" title="تشغيل">▶</button>
        <a class="hi-btn dl" href="${item.url}" download="${item.filename}" title="تنزيل">⬇</a>
      </div>
    `;
    el.querySelector('.hi-btn.play').addEventListener('click', e => {
      e.stopPropagation();
      playHistoryItem(item);
    });
    el.addEventListener('click', () => playHistoryItem(item));
    list.insertBefore(el, empty);
  }
}

function playHistoryItem(item) {
  loadPlayer(item.url, item, item.text || '');
  // Mark playing
  $$('.history-item').forEach(e => e.classList.remove('playing'));
  const el = Array.from($$('.history-item')).find(e => e.dataset.url === item.url);
  if (el) el.classList.add(`playing ${item.model}`);
  const audio = $('audio-el');
  audio.play();
}

function formatAgo(ts) {
  if (!ts) return '';
  const diff = Math.floor((Date.now() - ts) / 1000);
  if (diff < 60)   return `${diff}ث`;
  if (diff < 3600) return `${Math.floor(diff/60)}د`;
  if (diff < 86400)return `${Math.floor(diff/3600)}س`;
  return `${Math.floor(diff/86400)}ي`;
}

// ── Load server history on startup ────────────────────────────
async function loadServerHistory() {
  const existing = new Set(historyItems.map(i => i.filename));
  for (const mid of Object.keys(MODELS)) {
    try {
      const r = await fetch(`/api/${mid}/history?limit=30`);
      if (!r.ok) continue;
      const files = await r.json();
      for (const f of files) {
        if (!existing.has(f.filename)) {
          historyItems.push({
            filename:   f.filename,
            model:      mid,
            url:        `/audio/${mid}/${f.filename}`,
            text:       f.text || '',
            instruct:   f.instruct || '',
            params:     f.params || null,
            reference_text: f.reference_text || '',
            prompt_text:    f.prompt_text || '',
            duration_s: f.duration_s || 0,
            rtf:        f.rtf || 0,
            elapsed_s:  f.elapsed_s || 0,
            timestamp:  f.mtime * 1000,
          });
          existing.add(f.filename);
        }
      }
    } catch { /* worker offline */ }
  }
  historyItems.sort((a, b) => b.timestamp - a.timestamp);
  saveHistory();
  renderHistory();
}

// ── Compare selected models ───────────────────────────────────
function miniTitleHtml(mid) {
  const m = MODELS[mid];
  return `
    <div class="mini-player-title">
      <span>${m.icon} ${escapeHtml(m.name)}</span>
      <small>${escapeHtml(m.compareNote)}</small>
    </div>
  `;
}

// Final content for one compare mini-player — used both live and when restoring a saved run.
function miniPlayerHtml(mid, item, runId = null) {
  const options = item.options || optionSummary(mid, false);
  if (item.error) {
    return `
      ${miniTitleHtml(mid)}
      <div class="mini-player-meta error">خطأ: ${escapeHtml(String(item.error).slice(0, 120))}</div>
      <button class="mini-retry" data-run-id="${escapeAttr(runId || '')}" data-mid="${escapeAttr(mid)}" type="button">↻ إعادة المحاولة</button>
      ${optionChipsHtml(options)}
    `;
  }
  const url = item.url || `/audio/${mid}/${item.result.filename}`;
  return `
    ${miniTitleHtml(mid)}
    <audio controls preload="metadata" src="${escapeHtml(url)}"></audio>
    ${metricGridHtml(item.result)}
    <div class="mini-player-meta">${escapeHtml(MODELS[mid].role)}</div>
    ${optionChipsHtml(options)}
    ${sentInputHtml(item.result)}
  `;
}

function renderCompareSummary(grid, results) {
  const ok = results.filter(r => r.result);
  if (!ok.length) return;

  const byMetric = (key) => ok
    .filter(r => numeric(r.result[key]) !== null && numeric(r.result[key]) > 0)
    .sort((a, b) => numeric(a.result[key]) - numeric(b.result[key]))[0];
  const fastest = byMetric('elapsed_s');
  const bestRtf = byMetric('rtf');
  const highestRate = ok
    .filter(r => numeric(r.result.sample_rate) !== null)
    .sort((a, b) => numeric(b.result.sample_rate) - numeric(a.result.sample_rate))[0];

  const item = (label, row, value) => `
    <div class="summary-item">
      <span>${label}</span>
      <strong>${row ? escapeHtml(MODELS[row.mid].name) : '—'}</strong>
      <small>${escapeHtml(value || '—')}</small>
    </div>
  `;

  const summary = document.createElement('div');
  summary.className = 'compare-summary';
  summary.innerHTML = `
    <div class="summary-title">ملخص المقارنة</div>
    <div class="summary-grid">
      ${item('أسرع توليد', fastest, fastest ? formatSeconds(fastest.result.elapsed_s) : '')}
      ${item('أفضل RTF', bestRtf, bestRtf ? `${formatRtf(bestRtf.result.rtf)} · ${rtfProfile(bestRtf.result.rtf).label}` : '')}
      ${item('أعلى عينة', highestRate, highestRate ? formatSampleRate(highestRate.result.sample_rate) : '')}
      <div class="summary-item">
        <span>عدد النتائج</span>
        <strong>${ok.length}/${results.length}</strong>
        <small>${results.some(r => r.error) ? 'توجد أخطاء' : 'كلها اكتملت'}</small>
      </div>
    </div>
  `;
  grid.prepend(summary);
}

// ── Compare persistence (saved library of comparison runs) ────
const COMPARE_KEY      = 'tts_compare_v1';        // legacy single-run slot (migrated on load)
const COMPARE_RUNS_KEY = 'tts_compare_runs_v1';
const COMPARE_RUNS_MAX = 40;
let compareRuns = [];

function loadCompareRuns() {
  try {
    const arr = JSON.parse(localStorage.getItem(COMPARE_RUNS_KEY) || '[]');
    compareRuns = Array.isArray(arr) ? arr : [];
  } catch { compareRuns = []; }
  // One-time migration of the old single-slot run into the new list.
  if (!compareRuns.length) {
    try {
      const old = JSON.parse(localStorage.getItem(COMPARE_KEY) || 'null');
      if (old && Array.isArray(old.items) && old.items.length) {
        compareRuns = [{ id: `c${old.timestamp || Date.now()}`, text: old.text || '',
                         timestamp: old.timestamp || Date.now(), items: old.items }];
        persistCompareRuns();
      }
    } catch { /* ignore */ }
    try { localStorage.removeItem(COMPARE_KEY); } catch { /* ignore */ }
  }
  // A run interrupted by a reload may have left items mid-generation — surface them as
  // retryable errors instead of a stuck spinner.
  for (const run of compareRuns) {
    for (const item of run.items || []) {
      if (item.pending) { delete item.pending; if (!item.result) item.error = item.error || 'لم تكتمل المقارنة'; }
    }
  }
}

function persistCompareRuns() {
  try { localStorage.setItem(COMPARE_RUNS_KEY, JSON.stringify(compareRuns.slice(0, COMPARE_RUNS_MAX))); }
  catch { /* quota */ }
}

function addCompareRun(run) {
  compareRuns.unshift(run);
  if (compareRuns.length > COMPARE_RUNS_MAX) compareRuns = compareRuns.slice(0, COMPARE_RUNS_MAX);
  persistCompareRuns();
  renderCompareLibrary();
}

function deleteCompareRun(id) {
  compareRuns = compareRuns.filter(r => r.id !== id);
  persistCompareRuns();
  renderCompareLibrary();
}

function clearCompareRuns() {
  if (!compareRuns.length) return;
  if (!confirm('مسح كل المقارنات المحفوظة؟')) return;
  compareRuns = [];
  persistCompareRuns();
  renderCompareLibrary();
}

// Render one run's mini-players + "best of" summary into a container.
// Handles pending items (still generating) so the same renderer drives a live run.
function renderRunGrid(container, run) {
  container.innerHTML = '';
  for (const item of (run.items || []).filter(i => MODELS[i.mid])) {
    const mini = document.createElement('div');
    mini.className = `mini-player ${item.mid} ${item.pending ? '' : 'done'}`;
    mini.id = `mini-${run.id}-${item.mid}`;
    mini.innerHTML = item.pending
      ? `${miniTitleHtml(item.mid)}<div class="mini-spinner">في الانتظار…</div>${optionChipsHtml(item.options || optionSummary(item.mid, false))}`
      : miniPlayerHtml(item.mid, item, run.id);
    container.appendChild(mini);
  }
  renderCompareSummary(container, (run.items || []).filter(i => !i.pending && i.result));
}

// Replace one mini-player's content in place (used during live generation + retry).
function setMiniHtml(runId, mid, html) {
  const mini = $(`mini-${runId}-${mid}`);
  if (mini) mini.innerHTML = html;
}

// Rebuild a run's "best of" summary in place without touching its players.
function refreshRunSummary(run) {
  const first = (run.items || [])[0];
  const mini = first && $(`mini-${run.id}-${first.mid}`);
  const body = mini && mini.closest('.sc-body');
  if (!body) return;
  const old = body.querySelector('.compare-summary');
  if (old) old.remove();
  renderCompareSummary(body, (run.items || []).filter(i => !i.pending && i.result));
}

function toggleCompareRun(id) {
  if (expandedCompareRuns.has(id)) expandedCompareRuns.delete(id);
  else expandedCompareRuns.add(id);
  renderCompareLibrary();
}

function setAllCompareRunsExpanded(expand) {
  expandedCompareRuns = expand ? new Set(compareRuns.map(r => r.id)) : new Set();
  renderCompareLibrary();
}

// Re-run a single failed (or any) model in a comparison, reusing the same text + captured params.
async function retryCompareItem(runId, mid) {
  if (isComparing) { showToast('انتظر حتى تكتمل المقارنة الحالية', 'warn'); return; }
  const run = compareRuns.find(r => r.id === runId);
  if (!run) { showToast('تعذّر العثور على المقارنة', 'error'); return; }
  const idx = (run.items || []).findIndex(i => i.mid === mid);
  if (idx === -1) return;

  const prev = run.items[idx];
  const options = prev.options || optionSummary(mid, false);
  expandedCompareRuns.add(runId);   // make sure the run is visible while it retries
  setMiniHtml(runId, mid, `${miniTitleHtml(mid)}<div class="mini-spinner">جاري إعادة المحاولة…</div>${optionChipsHtml(options)}`);

  let item;
  try {
    const fd = buildFormDataForModel(mid, run.text, false, prev.params || null);
    const r = await fetch(`/api/${mid}/synthesize`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
    const result = await r.json();
    const url = `/audio/${mid}/${result.filename}`;
    addToHistory({ ...result, text: run.text, url, options, timestamp: Date.now() });
    item = { mid, result, options, url, params: prev.params };
    showToast('تمت إعادة التوليد ✓', 'success');
  } catch (e) {
    item = { mid, error: e.message, options, params: prev.params };
    showToast(`فشلت إعادة المحاولة: ${String(e.message).slice(0, 80)}`, 'error', 5000);
  }

  run.items[idx] = item;
  persistCompareRuns();
  setMiniHtml(runId, mid, miniPlayerHtml(mid, item, runId));
  refreshRunSummary(run);
}

// The library of comparisons (live + old), each expandable inline so several runs can be
// opened and listened to against each other.
function renderCompareLibrary() {
  const card = $('saved-compare-card');
  const list = $('saved-compare-list');
  if (!card || !list) return;
  if (!compareRuns.length) { card.hidden = true; list.innerHTML = ''; return; }
  card.hidden = false;

  // Toggle-all reflects whether everything is currently open.
  const toggleAll = $('btn-toggle-compares');
  if (toggleAll) {
    const allOpen = compareRuns.every(r => expandedCompareRuns.has(r.id));
    toggleAll.textContent = allOpen ? 'طيّ الكل' : 'فتح الكل';
    toggleAll.dataset.expand = allOpen ? '0' : '1';
  }

  list.innerHTML = '';
  for (const run of compareRuns) {
    const expanded = expandedCompareRuns.has(run.id);
    const icons = [...new Set((run.items || []).map(i => (MODELS[i.mid] || {}).icon || ''))].join(' ');
    const n = (run.items || []).length;
    const errs = (run.items || []).filter(i => i.error).length;
    const snippet = (run.text || '').slice(0, 70) || '—';
    const meta = `${icons} · ${n} نماذج${errs ? ` · ${errs} خطأ` : ''} · ${formatAgo(run.timestamp)}`;

    const itemEl = document.createElement('div');
    itemEl.className = `saved-compare-item ${expanded ? 'expanded' : ''}`;
    itemEl.dataset.id = run.id;

    const head = document.createElement('div');
    head.className = 'sc-head';
    head.innerHTML = `
      <span class="sc-caret">${expanded ? '▾' : '▸'}</span>
      <div class="sc-info">
        <div class="sc-snippet">${escapeHtml(snippet)}</div>
        <div class="sc-meta">${escapeHtml(meta)}</div>
      </div>
      <div class="sc-actions">
        <button class="hi-btn sc-del" title="حذف">🗑</button>
      </div>`;
    head.addEventListener('click', e => {
      if (e.target.closest('.sc-actions')) return;
      toggleCompareRun(run.id);
    });
    head.querySelector('.sc-del').addEventListener('click', e => { e.stopPropagation(); deleteCompareRun(run.id); });
    itemEl.appendChild(head);

    if (expanded) {
      const body = document.createElement('div');
      body.className = 'sc-body compare-grid';
      renderRunGrid(body, run);
      itemEl.appendChild(body);
    }
    list.appendChild(itemEl);
  }
}

async function compareModels() {
  if (isComparing) return;
  const text = $('text-input').value.trim();
  if (!text) { showToast('أدخل نصاً أولاً', 'warn'); return; }

  const selected = Array.from($$('#compare-checks input:checked')).map(e => e.value);
  if (!selected.length) { showToast('اختر نموذجاً واحداً على الأقل', 'warn'); return; }

  isComparing = true;
  const btn = $('btn-compare');
  btn.disabled = true;

  // Create the run up front and show it expanded at the top of the library, so the live
  // generation streams into the same card the user will keep and compare against later.
  // params snapshot per item lets a later retry reproduce these exact inputs.
  const run = {
    id: `c${Date.now()}`,
    text,
    timestamp: Date.now(),
    items: selected.map(mid => ({ mid, pending: true, options: optionSummary(mid, false), params: { ...paramValues[mid] } })),
  };
  currentCompareRunId = run.id;
  expandedCompareRuns.add(run.id);
  addCompareRun(run);   // unshift + persist + renderCompareLibrary → renders the pending card
  $('saved-compare-card').scrollIntoView({ behavior: 'smooth', block: 'start' });

  for (let i = 0; i < selected.length; i++) {
    const mid = selected[i];
    const idx = run.items.findIndex(it => it.mid === mid);
    const options = run.items[idx].options;
    $('compare-label').textContent = `جاري المقارنة ${i + 1}/${selected.length}`;
    setMiniHtml(run.id, mid, `${miniTitleHtml(mid)}<div class="mini-spinner">جاري التوليد…</div>${optionChipsHtml(options)}`);

    let item;
    try {
      const fd = buildFormDataForModel(mid, text, false);
      const r = await fetch(`/api/${mid}/synthesize`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const result = await r.json();
      const url = `/audio/${mid}/${result.filename}`;
      addToHistory({ ...result, text, url, options, timestamp: Date.now() });
      item = { mid, result, options, url, params: run.items[idx].params };
    } catch (e) {
      item = { mid, error: e.message, options, params: run.items[idx].params };
    }

    run.items[idx] = item;
    persistCompareRuns();
    setMiniHtml(run.id, mid, miniPlayerHtml(mid, item, run.id));
    refreshRunSummary(run);
  }

  isComparing = false;
  btn.disabled = false;
  updateCompareLabel();
  const hadErr = run.items.some(r => r.error);
  showToast(hadErr ? 'اكتملت المقارنة مع أخطاء' : 'اكتملت المقارنة', hadErr ? 'warn' : 'success');
}

// ── Accordion toggle ──────────────────────────────────────────
function setupAccordions() {
  $$('.acc-header').forEach(btn => {
    btn.addEventListener('click', () => {
      const body = $(btn.dataset.target);
      const section = btn.closest('.accordion');
      const isOpen  = !body.classList.contains('collapsed');
      body.classList.toggle('collapsed', isOpen);
      section.classList.toggle('open', !isOpen);
    });
  });
}

// ── Clear history ─────────────────────────────────────────────
function clearHistory() {
  if (!confirm('هل تريد مسح جميع سجلات التوليد؟')) return;
  historyItems = [];
  saveHistory();
  renderHistory();
}

// ── Init ──────────────────────────────────────────────────────
function init() {
  initParamValues();
  loadHistory();
  loadHistoryCollapsed();

  renderModelCards();
  renderStatusBadges();
  renderParams();
  renderTags();
  renderClonePanel();
  renderCompareChecks();
  renderSampleChips();
  renderComposePanel();
  renderHistory();
  loadCompareRuns();
  if (compareRuns[0]) expandedCompareRuns.add(compareRuns[0].id);  // open the latest after reload
  renderCompareLibrary();                              // comparisons library (live + old)
  setupAccordions();
  setupAudioEvents();

  // Text input events
  $('text-input').addEventListener('input', () => {
    invalidatePrepUndo();   // manual edits supersede the last prepare
    updateCharCount();
    updateSynthBtn();
    updateModelInputPreview();
  });

  // Synth button
  $('btn-synth').addEventListener('click', synthesize);

  // Auto-compose agent
  $('btn-compose-agent').addEventListener('click', composeWithAI);

  // Text-Prep agent (numbers→words / tashkeel toggles + prepare + before/after preview + undo)
  $('prep-normalize').addEventListener('click', e => togglePrepOption(e.currentTarget));
  $('prep-diacritize').addEventListener('click', e => togglePrepOption(e.currentTarget));
  $('btn-prep').addEventListener('click', prepareText);
  $('btn-prep-apply').addEventListener('click', applyPrep);
  $('btn-prep-cancel').addEventListener('click', cancelPrep);
  $('btn-prep-undo').addEventListener('click', undoPrep);

  // Clear text
  $('btn-clear-text').addEventListener('click', () => {
    $('text-input').value = '';
    invalidatePrepUndo();
    setPrepStatus('');
    updateCharCount();
    updateSynthBtn();
    updateModelInputPreview();
  });

  // Clear history
  $('btn-clear-history').addEventListener('click', clearHistory);

  // Collapse / expand history
  $('btn-toggle-history').addEventListener('click', toggleHistoryCollapsed);

  // Clear saved comparisons
  $('btn-clear-compares').addEventListener('click', clearCompareRuns);

  // Expand / collapse all saved comparisons
  $('btn-toggle-compares').addEventListener('click', e => {
    setAllCompareRunsExpanded(e.currentTarget.dataset.expand === '1');
  });

  // History filter
  $('history-filter').addEventListener('change', () => renderHistory());

  // Compare
  $('btn-compare').addEventListener('click', compareModels);

  // Retry a failed model inside any comparison (event-delegated on the library)
  $('saved-compare-list').addEventListener('click', e => {
    const btn = e.target.closest('.mini-retry');
    if (btn) { e.stopPropagation(); retryCompareItem(btn.dataset.runId, btn.dataset.mid); }
  });

  // Initial status poll + periodic refresh
  pollStatus();
  setInterval(pollStatus, 10_000);

  // Load server-side history after status check
  setTimeout(loadServerHistory, 1500);
}

document.addEventListener('DOMContentLoaded', init);
