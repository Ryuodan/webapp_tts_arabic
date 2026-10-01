'use strict';

// Resolve requests from the directory that served this script. The production UI lives
// below /arabic-tts/, so root-relative /api and /audio URLs bypassed the reverse proxy and
// left the status badges stuck on "checking". This also keeps local / development serving
// from / working without a separate configuration value.
const APP_BASE_URL = new URL('.', (document.currentScript && document.currentScript.src) || document.baseURI);
const appUrl = path => new URL(String(path || '').replace(/^\/+/, ''), APP_BASE_URL).toString();
const modelAudioUrl = (mid, filename) => appUrl(
  `audio/${encodeURIComponent(mid)}/${encodeURIComponent(filename)}`
);
// The gateway converts a stored wav on request, so every clip also downloads as MP3.
const mp3Url  = url => `${url}${String(url).includes('?') ? '&' : '?'}format=mp3`;
const mp3Name = filename => `${String(filename || 'audio').replace(/\.wav$/i, '')}.mp3`;

// ── Model definitions ────────────────────────────────────────
// The interface exposes two models: the Najdi fine-tune (house voice: Nasser) and the stock
// one. Both ride the SAME worker (gateway aliases -> port 8082); fixedParams.variant tells the
// worker which checkpoint to load. A model with `defaultVoice` clones that voice unless
// another is picked — the worker applies the same default, so API calls behave alike.
// VoxCPM2/Fish are retired from the interface.
// Every user-facing label below is a getter rather than a string: it re-resolves on each
// access, so flipping the interface language updates them without rebuilding these
// constants or touching the render sites that read `.label` / `.name`.
// ── Voice library ─────────────────────────────────────────────
// Built-in + uploaded clone voices, as the worker reports them (GET /api/voices). This
// starting list is the repo's built-ins — what the picker shows until that fetch lands —
// and MUST match voices/*/voice.json (ids, order and tags).
// Tags say what a voice is: its sex and dialect, whether the Najdi model trained on the
// speaker (`trained`) or only clones the clip (`unseen`), whether it is a synthetic or a
// human voice, and the kind of speaker.
let voiceCatalog = [
  { id: 'nasser',    custom: false, tags: ['male', 'najdi', 'trained', 'synthetic', 'support'] },
  { id: 'joud',      custom: false, tags: ['female', 'najdi', 'trained', 'synthetic', 'support'] },
  { id: 'rashed',    custom: false, tags: ['male', 'najdi', 'unseen', 'synthetic', 'support'] },
  { id: 'reem',      custom: false, tags: ['female', 'najdi', 'unseen', 'synthetic', 'support'] },
  { id: 'abeer',     custom: false, tags: ['female', 'saudi', 'unseen', 'human', 'artist'] },
  { id: 'sada_male', custom: false, tags: ['male', 'saudi', 'unseen', 'human', 'broadcast'] },
  { id: 'ahmed',     custom: false, tags: ['male', 'msa', 'unseen', 'reader'] },
];

// The picker's sections, in order: speakers the Najdi model trained on, voices it clones
// from their clip alone, and the user's own uploads.
const VOICE_GROUPS = ['trained', 'cloned', 'custom'];
function voiceGroup(v) {
  if (v.custom) return 'custom';
  return (v.tags || []).includes('trained') ? 'trained' : 'cloned';
}

// A tag's display name; an unknown key (a hand-edited voice.json) is shown as written.
function voiceTagLabel(key) {
  const translated = t(`vtag.${key}`);
  return translated !== `vtag.${key}` ? translated : key;
}

// Built-ins have translated names; an uploaded voice is called whatever its owner typed.
function voiceLabel(v) {
  const key = `voice.${v.id}`;
  const translated = t(key);
  return translated !== key ? translated : (v.label || v.id);
}

const OMNI_SHARED = {
  params: [
    { id: 'voice', get label() { return t('section.voice'); }, type: 'select', default: '',
      get options() {
        return [{ value: '', get label() { return t('voice.none'); } }]
          .concat(voiceCatalog.map(v => ({ value: v.id, get label() { return voiceLabel(v); } })));
      } },
  ],
  emotionTags: ['[laughter]'],   // base model only documents [laughter]; [applause] is unsupported
  cloneFields: [],
  formFields: {},
};

const MODELS = {
  omnivoice_najdi: {
    ...OMNI_SHARED,
    id: 'omnivoice_najdi',
    get name() { return t('model.najdi.name'); },
    icon: '🎙️',
    specs: '0.6B · 24kHz · Najdi FT v3 · step 1950',
    get role() { return t('model.najdi.role'); },
    get traits() { return [t('model.trait.najdi'), t('model.trait.nasserVoice'), t('model.trait.trainedVoices'), '24kHz']; },
    get profile() {
      return [
        { label: t('model.profile.bestUse'), value: t('model.najdi.bestUse') },
        { label: t('model.profile.control'), value: t('model.najdi.control') },
        { label: t('model.profile.note'),    value: t('model.najdi.note') },
      ];
    },
    get compareNote() { return t('model.najdi.compareNote'); },
    // Cloned when no other voice is picked — MUST match the worker's VARIANT_DEFAULT_VOICES.
    defaultVoice: 'nasser',
    fixedParams: { variant: 'najdi' },
  },
  omnivoice_base: {
    ...OMNI_SHARED,
    id: 'omnivoice_base',
    get name() { return t('model.base.name'); },
    icon: '🌐',
    specs: '0.6B · 24kHz · 600+ lang',
    get role() { return t('model.base.role'); },
    get traits() { return [t('model.trait.langs'), 'Arabic-ready', 'Voice design', '24kHz']; },
    get profile() {
      return [
        { label: t('model.profile.bestUse'), value: t('model.base.bestUse') },
        { label: t('model.profile.control'), value: t('model.control') },
        { label: t('model.profile.note'),    value: t('model.base.note') },
      ];
    },
    get compareNote() { return t('model.base.compareNote'); },
    fixedParams: { variant: 'base' },
  },
};

// ── Arabic dialects ───────────────────────────────────────────
// Language is locked to Arabic for every model; this picks the dialect that each
// worker injects via its native lever (OmniVoice instruct, VoxCPM2 prefix).
const DIALECTS = [
  { id: 'msa',      get label() { return t('dialect.msa'); } },
  { id: 'saudi',    get label() { return t('dialect.saudi'); } },
  { id: 'egyptian', get label() { return t('dialect.egyptian'); } },
];
const dialectLabel = id => (DIALECTS.find(d => d.id === id) || DIALECTS[0]).label;

// Optional voice persona (empty id = let the model decide), injected alongside the dialect.
const GENDERS = [
  { id: '',       get label() { return t('opt.auto'); } },
  { id: 'male',   get label() { return t('gender.male'); } },
  { id: 'female', get label() { return t('gender.female'); } },
];
const AGES = [
  { id: '',       get label() { return t('opt.auto'); } },
  { id: 'young',  get label() { return t('age.young'); } },
  { id: 'middle', get label() { return t('age.middle'); } },
  { id: 'old',    get label() { return t('age.old'); } },
];
const attrLabel = (list, id) => (list.find(o => o.id === id) || list[0]).label;

// OmniVoice picks the dialect via its native ISO 639-3 language code — MUST match the worker map.
const DIALECT_LANG = {
  msa: 'arb', saudi: 'ars', egyptian: 'arz',
};
const GENDER_EN = { male: 'male', female: 'female' };
const AGE_EN = { young: 'young adult', middle: 'middle-aged', old: 'elderly' };

// Auto-compose agent: job presets (ids MUST match compose.py JOBS).
const JOBS = [
  { id: 'customer_service', get label() { return t('persona.support'); } },
  { id: 'booking',          get label() { return t('persona.booking'); } },
  { id: 'storytelling',     get label() { return t('persona.story'); } },
  { id: 'announcement',     get label() { return t('persona.announce'); } },
];

// Reproduces each worker's injection so the user sees the exact string that reaches the model.
// Returns { text, instruct?, lang? } — `instruct`/`lang` are only present for OmniVoice.
function buildModelInput(mid, text) {
  const v = paramValues[mid] || {};
  const body = text || '';

  // Both interface models are OmniVoice variants and share the same injection:
  // dialect → language code (not instruct); instruct carries only valid EN voice-design tokens.
  const attrs = [];
  const sp = (v.speaker || '').trim();
  if (sp) attrs.push(sp);
  // When cloning, the reference clip already fixes the speaker's sex; the worker leaves
  // gender out of instruct then, so the preview must too.
  const cloning = Boolean(v.voice || MODELS[mid].defaultVoice);
  if (!cloning && GENDER_EN[v.gender]) attrs.push(GENDER_EN[v.gender]);
  if (AGE_EN[v.age]) attrs.push(AGE_EN[v.age]);
  return { text: body, instruct: attrs.join(', '), lang: DIALECT_LANG[v.dialect || 'msa'] || DIALECT_LANG.msa };
}

const SAMPLE_SENTENCES = [
  'مرحباً، كيف حالك؟',
  'أهلاً وسهلاً، يسعدنا تواجدكم معنا.',
  'أعلنت وزارة الصحة عن إطلاق حملة تطعيم وطنية شاملة.',
  'الذكاء الاصطناعي يُحدث ثورة في تحويل النص إلى كلام text-to-speech.',
  'اللغة العربية لغة سامية غنية بمفرداتها وتراثها الأدبي.',
];

// ── State ─────────────────────────────────────────────────────
let selectedModel = 'omnivoice_najdi';
let workerStatus  = Object.fromEntries(Object.keys(MODELS).map(mid => [mid, 'checking']));
let loadingModels = new Set();   // models with an in-flight /load request
let statusPollInFlight = false;
let statusPollTimer = null;
let currentAudioUrl = null;
let isGenerating  = false;
let isComparing   = false;
let audioCtx      = null;
let paramValues   = {};  // { omnivoice: {speaker: '', ...}, ... }
let manualOverride = {}; // { omnivoice: {enabled, text, instruct}, ... } — verbatim model-input edits
let cloneFiles    = {};  // { ref_audio: File|null, ref_text: '', ... }
let compareSelection = {};
let currentCompareRunId = null;  // id of the comparison run currently being generated (for retry)
let compareMode   = 'tashkeel';  // 'tashkeel': original vs tashkeel on one model; 'models': every model
let asrOnline     = false;       // the transcription worker is up (from the status poll)
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
  if (n === null || n <= 0) return { tone: 'neutral', label: t('rtf.unknown') };
  if (n <= 1) return { tone: 'fast', label: t('rtf.fast') };
  if (n <= 5) return { tone: 'ok', label: t('rtf.ok') };
  if (n <= 15) return { tone: 'slow', label: t('rtf.slow') };
  return { tone: 'very-slow', label: t('rtf.verySlow') };
}

function metricGridHtml(meta) {
  const rtf = rtfProfile(meta.rtf);
  return `
    <div class="metric-grid">
      <div class="metric-cell">
        <span class="metric-label">${t('metric.elapsed')}</span>
        <strong class="metric-value">${formatSeconds(meta.elapsed_s)}</strong>
      </div>
      <div class="metric-cell">
        <span class="metric-label">${t('metric.duration')}</span>
        <strong class="metric-value">${formatSeconds(meta.duration_s)}</strong>
      </div>
      <div class="metric-cell">
        <span class="metric-label">RTF</span>
        <strong class="metric-value rtf-${rtf.tone}">${formatRtf(meta.rtf)}</strong>
        <small>${rtf.label}</small>
      </div>
      <div class="metric-cell">
        <span class="metric-label">${t('metric.rate')}</span>
        <strong class="metric-value">${formatSampleRate(meta.sample_rate)}</strong>
      </div>
    </div>
  `;
}

function cloneLabel(key) {
  return {
    get ref_audio() { return t('clone.refAudio'); },
    get ref_text() { return t('clone.refText'); },
    get ref_wav() { return t('clone.refWav'); },
    get prompt_wav() { return t('clone.promptWav'); },
    get prompt_text() { return t('clone.promptText'); },
  }[key] || key;
}

const selectOptionValue = o => (o && typeof o === 'object') ? o.value : o;

function optionSummary(mid, includeClone = true) {
  const model = MODELS[mid];
  const vals = paramValues[mid] || {};
  const entries = (model.params || []).map(p => {
    const raw = Object.prototype.hasOwnProperty.call(vals, p.id) ? vals[p.id] : p.default;
    let value = typeof raw === 'string' && !raw.trim() ? t('misc.default') : raw;
    if (p.type === 'select') {
      const match = (p.options || []).find(o => selectOptionValue(o) == raw);
      if (match && typeof match === 'object') value = match.label;
    }
    return { label: p.label, value };
  });

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
    Object.assign(paramValues[mid], m.fixedParams || {});   // pinned values beat param defaults
    if (m.defaultVoice) paramValues[mid].voice = m.defaultVoice;
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
    const statusText = st === 'online'  ? t('st.online')
                     : st === 'offline' ? t('st.offline')
                     : st === 'checking' ? t('st.checking')
                     : isLoading        ? t('st.loading')
                                        : t('st.notLoaded');
    const statusCls = (st === 'loading' || st === 'checking') ? 'loading' : st;  // keep the blink while up-but-not-loaded
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
          ? `<button class="mc-load-btn" data-load="${m.id}" ${isLoading ? 'disabled' : ''}>${isLoading ? t('st.loadingBtn') : t('st.loadBtn')}</button>`
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
  showToast(t('st.loadingToast', { name }), '', 4000);
  try {
    const r = await fetch(appUrl(`api/${id}/load`), { method: 'POST' });
    if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
    loadingModels.delete(id);
    await pollStatus();                 // refresh badges immediately
    showToast(t('st.loadedToast', { name }), 'success');
  } catch (e) {
    loadingModels.delete(id);
    renderModelCards();
    showToast(t('st.loadFailed', { err: String(e.message).slice(0, 160) }), 'warn');
  }
}

// ── Render status badges ──────────────────────────────────────
function renderStatusBadges() {
  const row = $('status-row');
  row.innerHTML = '';
  for (const m of Object.values(MODELS)) {
    const st = workerStatus[m.id] || 'offline';
    const badge = document.createElement('div');
    badge.className = `status-badge ${st === 'checking' ? 'loading' : st}`;
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
  lock.title = t('lang.locked');
  lock.style.cssText = 'display:inline-flex;align-items:center;gap:4px;font-size:.72rem;font-weight:600;color:var(--txt2);background:#21262d;border:1px solid #30363d;border-radius:6px;padding:4px 8px';
  lock.textContent = t('lang.lockedChip');
  wrap.appendChild(lock);

  wrap.appendChild(makeAttrSelect(t('attr.dialect'), 'dialect', DIALECTS));
  wrap.appendChild(makeAttrSelect(t('attr.gender'), 'gender', GENDERS));
  wrap.appendChild(makeAttrSelect(t('attr.age'), 'age', AGES));
  body.appendChild(wrap);

  const hint = document.createElement('div');
  hint.className = 'param-hint';
  hint.style.marginBottom = '8px';
  hint.textContent = t('lang.lockedHint');
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
      <span style="font-size:.7rem;color:var(--txt2);font-weight:700">${t('ov.title')}</span>
      <button type="button" id="btn-input-override" class="tag-chip" style="flex-shrink:0">
        ${ov.enabled ? t('ov.revert') : t('ov.edit')}
      </button>
    </div>`;

  if (!ov.enabled) {
    if (mi.instruct !== undefined) {
      const v = paramValues[selectedModel] || {};
      html += codeLineHtml(t('ov.langLine'), `${mi.lang} · ${t('ov.arabic')} (${dialectLabel(v.dialect || 'msa')})`);
      html += codeLineHtml(t('ov.instruct'), mi.instruct);
      html += codeLineHtml(t('ov.text'), mi.text);
    } else {
      html += codeLineHtml(t('ov.textSent'), mi.text);
    }
    el.innerHTML = html;
  } else {
    if (mi.instruct !== undefined) html += editLineHtml(t('ov.instruct'), 'ov-instruct');
    html += editLineHtml(t('ov.text'), 'ov-text');
    const langNote = mi.lang
      ? t('ov.noteDialect')
      : t('ov.notePlain');
    html += `<div class="param-hint" style="margin-top:6px">${escapeHtml(t('ov.hint', { note: langNote }))}</div>`;
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
      <div style="font-size:.7rem;color:var(--txt2);font-weight:700">${t('ov.sent')}</div>
      ${meta.model_instruct ? codeLineHtml(t('ov.instruct'), meta.model_instruct) : ''}
      ${codeLineHtml(t('ov.text'), meta.model_input)}
    </div>`;
}

function renderParams() {
  const body = $('params-body');
  if (!body) return;
  const model = MODELS[selectedModel];
  body.innerHTML = renderModelInsights(model);
  renderLanguageBar(body);

  if (!model.params.length) {
    body.insertAdjacentHTML('beforeend', `<p class="param-empty">${t('misc.noParams')}</p>`);
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

function renderVoicePicker() {
  const select = $('voice-select');
  if (!select) return;

  const model = MODELS[selectedModel];
  const voiceParam = (model.params || []).find(p => p.id === 'voice');
  if (!voiceParam) {
    select.innerHTML = `<option value="">${t('voice.none')}</option>`;
    select.disabled = true;
    return;
  }

  const current = currentVoiceId(selectedModel);
  const option = (value, label) => `
    <option value="${escapeHtml(String(value))}" ${value === current ? 'selected' : ''}>
      ${escapeHtml(label)}
    </option>`;
  // A model with a house voice always clones someone, so "no cloning" is not offered there.
  const none = model.defaultVoice ? '' : option('', t('voice.none'));
  const groups = VOICE_GROUPS.map(group => {
    const members = voiceCatalog.filter(v => voiceGroup(v) === group);
    if (!members.length) return '';
    return `<optgroup label="${escapeHtml(t(`voice.group.${group}`))}">
      ${members.map(v => option(v.id, voiceLabel(v))).join('')}</optgroup>`;
  });
  select.disabled = false;
  select.innerHTML = none + groups.join('');

  // One voice choice for every model, so a cross-model comparison hears the same speaker.
  select.onchange = e => {
    for (const mid of Object.keys(MODELS)) {
      if (paramValues[mid]) paramValues[mid].voice = e.target.value;
    }
    renderVoiceDetails();
  };
  renderVoiceDetails();
}

// The voice a model will clone: the picked one while it still exists, else its house voice.
function currentVoiceId(mid) {
  const picked = (paramValues[mid] || {}).voice || '';
  if (picked && voiceCatalog.some(v => v.id === picked)) return picked;
  return MODELS[mid].defaultVoice || '';
}

function selectedVoice() {
  const id = currentVoiceId(selectedModel);
  return voiceCatalog.find(v => v.id === id) || null;
}

function voiceNameFor(id) {
  const v = voiceCatalog.find(x => x.id === id);
  return v ? voiceLabel(v) : (id || '');
}

// Under the picker: what the selected voice is, and whether it can be deleted.
function renderVoiceDetails() {
  const v = selectedVoice();
  const preview = $('btn-voice-preview');
  const del = $('btn-voice-delete');
  const hint = $('voice-hint');
  if (preview) preview.disabled = !v;
  if (del) del.hidden = !(v && v.custom);
  const tags = $('voice-tags');
  if (tags) {
    tags.innerHTML = ((v && v.tags) || []).map(key => {
      const tip = t(`vtag.${key}.tip`);
      return `<span class="voice-tag${/^[a-z_]+$/.test(key) ? ` vt-${key}` : ''}"
        ${tip !== `vtag.${key}.tip` ? `title="${escapeHtml(tip)}"` : ''}>${escapeHtml(voiceTagLabel(key))}</span>`;
    }).join('');
  }
  if (!hint) return;
  if (!v) { hint.textContent = t('voice.noneHint'); return; }
  const bits = [v.custom ? t('voice.custom') : t('voice.builtin')];
  if (v.duration_s) bits.push(`${Number(v.duration_s).toFixed(1)} s`);
  const said = v.ref_text ? `«${v.ref_text}»` : (v.custom ? t('voice.noText') : '');
  hint.textContent = bits.join(' · ') + (said ? ` — ${said}` : '');
}

// ── Render emotion tags ───────────────────────────────────────
function renderTags() {
  const strip = $('tag-strip');
  if (!strip) return;
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
    btn.title = t('tag.add');
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
  if (!body) return;
  const model = MODELS[selectedModel];
  body.innerHTML = '';

  if (model.cloneHint) {
    const hint = document.createElement('p');
    hint.style.cssText = 'font-size:.72rem;color:var(--txt2);margin-bottom:6px;direction:rtl;line-height:1.5';
    hint.textContent = model.cloneHint;
    body.appendChild(hint);
  }

  // Every interface model is an OmniVoice variant with the same cloning fields.
  body.appendChild(makeFileZone('ref_audio', t('clone.zoneLabel'), 'audio/wav,audio/*'));
  body.appendChild(makeTextRow('ref_text', t('clone.textLabel'), t('clone.textPh')));
}

function makeFileZone(key, label, accept) {
  const wrap = document.createElement('div');
  wrap.className = 'clone-row';
  wrap.innerHTML = `<div class="clone-row-label">${label}</div>`;

  const zone = document.createElement('div');
  zone.className = 'file-zone';
  zone.dataset.key = key;
  zone.innerHTML = `<span class="zone-label">${t('clone.drop')}</span><input type="file" accept="${accept}">`;

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
  if (!container) return;
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

// Reflect the compare mode and what it will generate on the compare button.
function updateCompareLabel() {
  if (isComparing) return;
  const btn = $('btn-compare');
  if (!btn) return;
  const label = $('compare-label');
  const hint = $('compare-hint');
  const up = mid => !['offline', 'checking'].includes(workerStatus[mid]);
  let ready;
  if (compareMode === 'tashkeel') {
    ready = up(selectedModel);
    if (label) label.textContent = t('cmp.runTashkeel');
    if (hint) hint.textContent = t(tashkeelMarks === 'shadda' ? 'cmp.hintShadda' : 'cmp.hintTashkeel',
                                   { model: MODELS[selectedModel].name });
  } else {
    const n = Object.keys(MODELS).filter(up).length;
    ready = n > 0;
    if (label) label.textContent = n ? t('cmp.runN', { n }) : t('cmp.none');
    if (hint) hint.textContent = t('cmp.hintModels', {
      variant: variantLabel(speakVariant === 'tashkeel' ? markedVariant() : 'original') });
  }
  // Keep the button clickable with empty text so the user gets an explanatory toast
  // instead of an inert control that looks broken.
  btn.disabled = !ready || isGenerating || isComparing;
}

const COMPARE_MODE_KEY = 'tts_compare_mode_v1';

function setCompareMode(mode) {
  compareMode = mode === 'models' ? 'models' : 'tashkeel';
  try { localStorage.setItem(COMPARE_MODE_KEY, compareMode); } catch { /* private mode */ }
  for (const [id, m] of [['cmp-mode-tashkeel', 'tashkeel'], ['cmp-mode-models', 'models']]) {
    const el = $(id);
    if (!el) continue;
    el.classList.toggle('active', compareMode === m);
    el.setAttribute('aria-checked', String(compareMode === m));
  }
  updateCompareLabel();
}

function setupCompareModes() {
  if (!$('cmp-mode-tashkeel')) return;
  let saved = 'tashkeel';
  try { saved = localStorage.getItem(COMPARE_MODE_KEY) || 'tashkeel'; } catch { /* private mode */ }
  $('cmp-mode-tashkeel').addEventListener('click', () => setCompareMode('tashkeel'));
  $('cmp-mode-models').addEventListener('click', () => setCompareMode('models'));
  setCompareMode(saved);
}

function updateCompareMode() {
  const toggle = $('use-all-models');
  const enabled = !toggle || toggle.checked;
  const btn = $('btn-compare');
  if (btn) btn.hidden = !enabled;
  updateCompareLabel();
}

// ── Render sample chips ───────────────────────────────────────
function renderSampleChips() {
  const container = $('sample-chips');
  if (!container) return;
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

// One inline status line under an agent's controls — '', 'success' or 'error'.
function setStatusLine(id, msg, type = '') {
  const el = $(id);
  if (el) { el.textContent = msg || ''; el.className = `compose-status ${type}`; }
}

function setComposeStatus(msg, type = '') { setStatusLine('compose-status', msg, type); }

// Ask the agent to write one Arabic script and configure BOTH engines from the chosen inputs.
async function composeWithAI() {
  const btn = $('btn-compose-agent');
  if (btn.disabled) return;

  btn.disabled = true;
  $('compose-agent-label').textContent = t('ag.composing');
  setComposeStatus(t('ag.composeBusy'));
  try {
    const r = await fetch(appUrl('api/compose'), {
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
    setComposeStatus(result.notes ? `✓ ${result.notes}` : t('ag.composeDone'), 'success');
    showToast(t('ag.composeToast'), 'success');
  } catch (e) {
    setComposeStatus(`${t('misc.error')}: ${String(e.message).slice(0, 220)}`, 'error');
    showToast(t('ag.composeFailed'), 'error', 5000);
  } finally {
    btn.disabled = false;
    $('compose-agent-label').textContent = t('ag.compose');
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
    Object.assign(v, MODELS[mid].fixedParams || {});   // pinned values beat the agent's too
    if (manualOverride[mid]) manualOverride[mid].enabled = false;
  }
  // Same instruct for every OmniVoice variant (compose's voxcpm2 fields are unused now).
  for (const mid of Object.keys(MODELS)) paramValues[mid].speaker = result.omnivoice_instruct || '';

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

function setPrepStatus(msg, type = '') { setStatusLine('prep-status', msg, type); }

function togglePrepOption(btn) {
  const on = btn.dataset.on !== '1';
  btn.dataset.on = on ? '1' : '0';
  btn.classList.toggle('active', on);
}

async function prepareText() {
  const btn  = $('btn-prep');
  if (btn.disabled) return;
  const text = $('text-input').value.trim();
  if (!text) { showToast(t('ag.noText'), 'error'); return; }

  const normalize  = $('prep-normalize').dataset.on === '1';
  const diacritize = $('prep-diacritize').dataset.on === '1';
  if (!normalize && !diacritize) {
    setPrepStatus(t('ag.pickOption'), 'error');
    return;
  }

  btn.disabled = true;
  $('prep-label').textContent = t('ag.preparing');
  setPrepStatus(t('ag.prepBusy'));
  try {
    const r = await fetch(appUrl('api/prepare'), {
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
    setPrepStatus(result.notes ? `✓ ${result.notes}` : t('ag.prepDone'), 'success');
  } catch (e) {
    setPrepStatus(`${t('misc.error')}: ${String(e.message).slice(0, 220)}`, 'error');
    showToast(t('ag.prepFailed'), 'error', 5000);
  } finally {
    btn.disabled = false;
    $('prep-label').textContent = t('ag.prep');
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
  showToast(t('ag.applied'), 'success');
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

// ── Transcription agent (ASR) ─────────────────────────────────
// Audio → text, feeding the synthesis box. (The reference-text hand-off is gone with
// the clone panel — simplified mode has no field to drop a transcript into.)
let transcribeFile = null;   // the picked audio File
let transcriptText = '';     // last successful transcript

function setTranscribeStatus(msg, type = '') { setStatusLine('transcribe-status', msg, type); }

async function transcribeAudio() {
  const btn = $('btn-transcribe');
  if (btn.disabled) return;
  if (!transcribeFile) { setTranscribeStatus(t('tr.needFile'), 'error'); return; }

  const fd = new FormData();
  fd.append('audio', transcribeFile, transcribeFile.name);
  fd.append('language', $('transcribe-lang').value);
  fd.append('punctuation', $('transcribe-punct').dataset.on === '1');

  btn.disabled = true;
  $('transcribe-label').textContent = t('tr.running');
  setTranscribeStatus(t('tr.busy'));
  try {
    const r = await fetch(appUrl('api/transcribe'), { method: 'POST', body: fd });
    if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
    const res = await r.json();

    transcriptText = (res.text || '').trim();
    $('transcribe-text').textContent = transcriptText || t('tr.empty');
    $('transcribe-result').hidden = false;
    setTranscribeStatus(
      `✓ ${formatSeconds(res.duration_s)} ${t('badge.audio')} → ${formatSeconds(res.elapsed_s)} · RTF ${formatRtf(res.rtf)}`,
      'success');
  } catch (e) {
    setTranscribeStatus(`${t('misc.error')}: ${String(e.message).slice(0, 220)}`, 'error');
    showToast(t('tr.failed'), 'error', 5000);
  } finally {
    btn.disabled = false;
    $('transcribe-label').textContent = t('tr.run');
  }
}

// Drop the transcript into the synthesis box.
function useTranscriptAsText() {
  if (!transcriptText) return;
  $('text-input').value = transcriptText;
  showToast(t('tr.moved'), 'success');
  updateCharCount();
  updateSynthBtn();
}

// One place to accept audio, whether it was picked from disk or just recorded.
function setTranscribeFile(file, label) {
  const zone = $('transcribe-zone');
  if (!file || !zone) return;
  transcribeFile = file;
  zone.classList.add('has-file');
  zone.querySelector('.zone-label').textContent = `✓ ${label || file.name}`;
  setTranscribeStatus('');
}

// Mic capture into the same File the picker would have produced. The button is revealed
// only when recording is actually possible, so it never dead-ends the user: getUserMedia
// is absent outside a secure context (plain http on a LAN address hides it entirely).
function setupRecorder() {
  const btn = $('btn-record');
  if (!btn || typeof MicRecorder === 'undefined') return;
  if (!MicRecorder.supported() || !window.isSecureContext) return;

  btn.hidden = false;
  let handle = null;
  let timer = null;

  const idle = () => {
    btn.textContent = t('tr.record');
    btn.classList.remove('active', 'recording');
    clearInterval(timer);
    timer = null;
  };

  btn.addEventListener('click', async () => {
    if (handle) {                       // second click: stop and keep the clip
      const active = handle;
      handle = null;
      idle();
      try {
        const file = await active.stop();
        const secs = formatSeconds((Date.now() - active.startedAt) / 1000);
        setTranscribeFile(file, `${t('tr.clip')} ${secs}`);
      } catch (e) {
        setTranscribeStatus(String(e.message), 'error');
      }
      return;
    }

    try {
      handle = await MicRecorder.start();
    } catch (e) {
      setTranscribeStatus(String(e.message), 'error');
      showToast(t('tr.recordFailed'), 'error', 5000);
      return;
    }
    btn.textContent = t('tr.stop');
    btn.classList.add('active', 'recording');
    timer = setInterval(() => {
      setTranscribeStatus(`${t('tr.recording')} ${MicRecorder.fmtElapsed(Date.now() - handle.startedAt)}`);
    }, 250);
  });
}

// Wire the panel. Every lookup is guarded: the transcription section is optional markup,
// and a page without it must still boot the primary controls.
function setupTranscription() {
  const zone = $('transcribe-zone');
  const button = $('btn-transcribe');
  if (!zone || !button) return;

  zone.querySelector('input').addEventListener('change', e => {
    setTranscribeFile(e.target.files[0]);
  });
  $('transcribe-punct').addEventListener('click', e => togglePrepOption(e.currentTarget));
  button.addEventListener('click', transcribeAudio);
  $('btn-transcribe-use').addEventListener('click', useTranscriptAsText);
  setupRecorder();
}

// The detail of a failed request, as the gateway phrases it, rather than a JSON blob.
async function errorText(r) {
  const raw = await r.text();
  try {
    const detail = JSON.parse(raw).detail;
    if (detail) return typeof detail === 'string' ? detail : JSON.stringify(detail);
  } catch { /* not JSON */ }
  return raw || `HTTP ${r.status}`;
}

// ── Voice library actions ─────────────────────────────────────
// Listing, previewing, adding and deleting clone voices. The worker stores uploaded ones
// outside the repo (TTS_WORKDIR), so they survive restarts and a `git pull`.
let voiceUpload = null;          // the File picked in the add-voice form

async function loadVoices() {
  try {
    const r = await fetch(appUrl('api/voices'), { cache: 'no-store' });
    if (r.ok) {
      const data = await r.json();
      if (Array.isArray(data.voices) && data.voices.length) voiceCatalog = data.voices;
    }
  } catch { /* worker down — keep the list we have */ }
  // A voice deleted elsewhere falls back to each model's own default.
  for (const mid of Object.keys(MODELS)) {
    const picked = paramValues[mid] && paramValues[mid].voice;
    if (picked && !voiceCatalog.some(v => v.id === picked)) {
      paramValues[mid].voice = MODELS[mid].defaultVoice || '';
    }
  }
  renderVoicePicker();
}

// The status poll carries the worker's voice ids; refetch only when that set changed.
function syncVoicesWithStatus(data) {
  const info = data && (data.omnivoice_najdi || data.omnivoice_base);
  if (!info || !Array.isArray(info.voices)) return;
  const known = voiceCatalog.map(v => v.id).sort().join();
  if (info.voices.slice().sort().join() !== known) loadVoices();
}

function toggleVoicePreview() {
  const v = selectedVoice();
  const audio = $('voice-preview-audio');
  if (!v || !audio) return;
  if (!audio.paused && audio.dataset.voice === v.id) { audio.pause(); return; }
  audio.src = appUrl(`api/voices/${encodeURIComponent(v.id)}/audio`);
  audio.dataset.voice = v.id;
  audio.play().catch(e => showToast(`${t('misc.error')}: ${e.message}`, 'error'));
}

async function deleteSelectedVoice() {
  const v = selectedVoice();
  if (!v || !v.custom) return;
  const name = voiceLabel(v);
  if (!confirm(t('voice.confirmDelete', { name }))) return;
  try {
    const r = await fetch(appUrl(`api/voices/${encodeURIComponent(v.id)}`), { method: 'DELETE' });
    if (!r.ok) throw new Error(await errorText(r));
    showToast(t('voice.deleted', { name }), 'success');
  } catch (e) {
    showToast(`${t('misc.error')}: ${e.message}`, 'error', 6000);
  }
  await loadVoices();
}

function openVoiceForm(open) {
  $('voice-add').hidden = !open;
  $('btn-voice-add').hidden = open;
  if (open) { $('voice-name').focus(); return; }
  voiceUpload = null;
  $('voice-name').value = '';
  $('voice-text').value = '';
  const zone = $('voice-zone');
  zone.classList.remove('has-file');
  zone.querySelector('.zone-label').textContent = t('voice.drop');
  zone.querySelector('input').value = '';
  setStatusLine('voice-status', '');
}

// Picking a clip names the voice after the file (editable) and transcribes it, since the
// clone needs to know what is said in its reference.
function setVoiceFile(file) {
  if (!file) return;
  voiceUpload = file;
  const zone = $('voice-zone');
  zone.classList.add('has-file');
  zone.querySelector('.zone-label').textContent = `✓ ${file.name}`;
  if (!$('voice-name').value.trim()) $('voice-name').value = file.name.replace(/\.[^.]+$/, '');
  if ($('voice-text').value.trim()) return;
  // The gateway evicts the TTS model to make room for transcription, so only go ahead
  // when the transcription worker is actually there to use that room.
  if (asrOnline) transcribeVoiceClip();
  else setStatusLine('voice-status', t('voice.asrOffline'), 'warn');
}

async function transcribeVoiceClip() {
  if (!voiceUpload) { setStatusLine('voice-status', t('voice.needFile'), 'warn'); return; }
  const btn = $('btn-voice-transcribe');
  btn.disabled = true;
  setStatusLine('voice-status', t('voice.transcribing'));
  try {
    const fd = new FormData();
    fd.append('audio', voiceUpload, voiceUpload.name);
    fd.append('language', 'ar');
    fd.append('punctuation', 'true');
    const r = await fetch(appUrl('api/transcribe'), { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await errorText(r));
    const text = ((await r.json()).text || '').trim();
    if (text) {
      $('voice-text').value = text;
      setStatusLine('voice-status', t('voice.transcribed'), 'success');
    } else {
      setStatusLine('voice-status', t('voice.noSpeech'), 'warn');
    }
  } catch (e) {
    setStatusLine('voice-status', t('voice.transcribeFailed', { err: String(e.message).slice(0, 120) }), 'error');
  } finally {
    btn.disabled = false;
  }
}

async function saveVoice() {
  const name = $('voice-name').value.trim();
  if (!name) { setStatusLine('voice-status', t('voice.needName'), 'warn'); return; }
  if (!voiceUpload) { setStatusLine('voice-status', t('voice.needFile'), 'warn'); return; }
  const btn = $('btn-voice-save');
  btn.disabled = true;
  setStatusLine('voice-status', t('voice.saving'));
  try {
    const fd = new FormData();
    fd.append('name', name);
    fd.append('audio', voiceUpload, voiceUpload.name);
    fd.append('ref_text', $('voice-text').value.trim());
    const r = await fetch(appUrl('api/voices'), { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await errorText(r));
    const voice = await r.json();
    await loadVoices();
    for (const mid of Object.keys(MODELS)) paramValues[mid].voice = voice.id;   // use it right away
    renderVoicePicker();
    openVoiceForm(false);
    showToast(t('voice.saved', { name: voice.label }), 'success');
  } catch (e) {
    setStatusLine('voice-status', String(e.message).slice(0, 160), 'error');
  } finally {
    btn.disabled = false;
  }
}

function setupVoiceLibrary() {
  if (!$('voice-add')) return;
  $('btn-voice-preview').addEventListener('click', toggleVoicePreview);
  $('btn-voice-delete').addEventListener('click', deleteSelectedVoice);
  $('btn-voice-add').addEventListener('click', () => openVoiceForm(true));
  $('btn-voice-cancel').addEventListener('click', () => openVoiceForm(false));
  $('btn-voice-transcribe').addEventListener('click', transcribeVoiceClip);
  $('btn-voice-save').addEventListener('click', saveVoice);
  $('voice-zone').querySelector('input').addEventListener('change', e => setVoiceFile(e.target.files[0]));

  const audio = $('voice-preview-audio');
  const btn = $('btn-voice-preview');
  const label = () => { btn.textContent = audio.paused ? t('voice.preview') : t('voice.stop'); };
  ['play', 'pause', 'ended'].forEach(ev => audio.addEventListener(ev, label));
  loadVoices();
}

// ── Tashkeel agent ────────────────────────────────────────────
// A diacritized copy of the text box, made by the Text-Prep agent (POST /api/prepare with
// tashkeel only). It sits beside the original rather than replacing it, so Generate can
// speak either one and Compare can play the two side by side.
// `source` is the original it was made from; `full` and `shadda` are the two forms the agent
// returned for it, and `text` is the one on screen (hand edits included).
let tashkeel = { source: '', text: '', full: '', shadda: '' };
let speakVariant = 'original';             // which version Generate speaks
// Which marks the agent's copy carries: the whole tashkeel, or the shadda alone.
const TASHKEEL_MARKS_KEY = 'tts_tashkeel_marks';
let tashkeelMarks = 'full';
// What a run spoken from the agent's copy is called: 'tashkeel' or 'shadda'.
const markedVariant = () => (tashkeelMarks === 'shadda' ? 'shadda' : 'tashkeel');

const VARIANT_LABELS = { tashkeel: 'tk.tashkeel', shadda: 'tk.shadda' };
const variantLabel = variant => t(VARIANT_LABELS[variant] || 'tk.original');
const variantBadgeHtml = variant =>
  `<span class="variant-badge ${VARIANT_LABELS[variant] ? 'tashkeel' : 'original'}">${escapeHtml(variantLabel(variant))}</span>`;

// Harakat (tanwin … sukun) per Arabic letter: diacritized text runs near one per letter,
// ordinary text has only the odd tanwin or shadda. Tells older runs apart after the fact.
function hasTashkeel(text) {
  const s = String(text || '');
  const letters = (s.match(/[\u0621-\u064A]/g) || []).length;
  const marks = (s.match(/[\u064B-\u0652]/g) || []).length;
  return letters > 0 && marks / letters > 0.3;
}

// The Najdi card's text is Najdi speech, so its tashkeel follows that register, not MSA's.
function tashkeelDialect() {
  if (selectedModel === 'omnivoice_najdi') return 'saudi';
  return (paramValues[selectedModel] || {}).dialect || 'msa';
}

async function makeTashkeel(original) {
  const text = (original !== undefined ? original : $('text-input').value).trim();
  if (!text) { showToast(t('synth.needText'), 'warn'); return null; }
  const btn = $('btn-tashkeel');
  if (btn) btn.disabled = true;
  setStatusLine('tashkeel-status', t('tk.running'));
  try {
    const r = await fetch(appUrl('api/prepare'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, dialect: tashkeelDialect(), normalize: false, diacritize: true,
                             marks: tashkeelMarks }),
    });
    if (!r.ok) throw new Error(await errorText(r));
    const data = await r.json();
    const out = (data.diacritized || '').trim();
    if (!out) throw new Error(t('tk.empty'));
    // Both forms come back from the one call, so switching marks needs no second one.
    tashkeel = { source: text, text: out,
                 full: (data.diacritized_full || '').trim(),
                 shadda: (data.diacritized_shadda || '').trim() };
    renderTashkeel();
    // The agent retries once when it rewrites a word; if it still did, say so before the
    // user compares two sentences that differ by more than their harakat.
    if (data.letters_changed) setStatusLine('tashkeel-status', t('tk.changed'), 'warn');
    else if (tashkeelMarks === 'shadda' && out === text) setStatusLine('tashkeel-status', t('tk.noShadda'), 'warn');
    else setStatusLine('tashkeel-status', t(tashkeelMarks === 'shadda' ? 'tk.doneShadda' : 'tk.doneBy',
                                            { model: data.model || '' }), 'success');
    return out;
  } catch (e) {
    const msg = String(e.message).slice(0, 200);
    setStatusLine('tashkeel-status', msg, 'error');
    showToast(t('tk.failed', { err: msg }), 'error', 7000);
    return null;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// The tashkeel for `original`, made now if the one on screen belongs to older text.
async function ensureTashkeel(original) {
  if (tashkeel.text && tashkeel.source === original) return tashkeel.text;
  return makeTashkeel(original);
}

// What Generate speaks. Throws when the tashkeel it needs could not be made.
async function textToSpeak(original) {
  if (speakVariant !== 'tashkeel') return { text: original, variant: 'original' };
  $('progress-hint').textContent = t('tk.running');
  const text = await ensureTashkeel(original);
  if (!text) throw new Error(t('tk.needed'));
  return { text, variant: markedVariant() };
}

// Full tashkeel or the shadda alone. A copy already made for this text is swapped for its
// other form on the spot; anything typed into the box since is replaced by it.
function setTashkeelMarks(marks) {
  tashkeelMarks = marks === 'shadda' ? 'shadda' : 'full';
  try { localStorage.setItem(TASHKEEL_MARKS_KEY, tashkeelMarks); } catch { /* private mode */ }
  const other = tashkeel[tashkeelMarks];
  if (tashkeel.text && other) tashkeel.text = other;
  else if (tashkeel.text) tashkeel = { source: '', text: '', full: '', shadda: '' };   // made before both forms existed
  renderTashkeel();
  updateSynthBtn();
}

function setSpeakVariant(variant) {
  speakVariant = variant === 'tashkeel' ? 'tashkeel' : 'original';
  renderTashkeel();
  updateSynthBtn();
}

function renderTashkeel() {
  const box = $('tashkeel-box');
  if (!box) return;
  box.hidden = !tashkeel.text;
  const area = $('tashkeel-text');
  if (area.value !== tashkeel.text) area.value = tashkeel.text;
  const original = $('text-input').value.trim();
  $('tashkeel-stale').hidden = !tashkeel.text || tashkeel.source === original;
  for (const [id, variant] of [['speak-original', 'original'], ['speak-tashkeel', 'tashkeel']]) {
    const on = speakVariant === variant;
    $(id).classList.toggle('active', on);
    $(id).setAttribute('aria-checked', String(on));
  }
  for (const [id, marks] of [['tk-marks-full', 'full'], ['tk-marks-shadda', 'shadda']]) {
    if (!$(id)) continue;
    $(id).classList.toggle('active', tashkeelMarks === marks);
    $(id).setAttribute('aria-checked', String(tashkeelMarks === marks));
  }
  // The box and the "speaks" choice are named after the marks they carry.
  if ($('tashkeel-tag')) $('tashkeel-tag').textContent = t(tashkeelMarks === 'shadda' ? 'tk.shadda' : 'tk.tag');
  $('speak-tashkeel').textContent = variantLabel(markedVariant());
}

function setupTashkeel() {
  if (!$('btn-tashkeel')) return;
  $('btn-tashkeel').addEventListener('click', () => makeTashkeel());
  // Hand edits to the diacritized copy are kept — it is what gets spoken.
  $('tashkeel-text').addEventListener('input', e => { tashkeel.text = e.target.value; });
  $('speak-original').addEventListener('click', () => setSpeakVariant('original'));
  $('speak-tashkeel').addEventListener('click', () => setSpeakVariant('tashkeel'));
  $('text-input').addEventListener('input', renderTashkeel);
  if ($('tk-marks-full')) {
    try { tashkeelMarks = localStorage.getItem(TASHKEEL_MARKS_KEY) === 'shadda' ? 'shadda' : 'full'; } catch { /* private mode */ }
    $('tk-marks-full').addEventListener('click', () => setTashkeelMarks('full'));
    $('tk-marks-shadda').addEventListener('click', () => setTashkeelMarks('shadda'));
    renderTashkeel();
  }
}

// ── Select model ──────────────────────────────────────────────
function selectModel(id) {
  selectedModel = id;
  cloneFiles = {};
  renderModelCards();
  renderVoicePicker();
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
  const useAll = Boolean($('use-all-models') && $('use-all-models').checked);
  const states = Object.keys(MODELS).map(mid => workerStatus[mid]);
  const checking = useAll
    ? states.every(st => st === 'checking')
    : workerStatus[selectedModel] === 'checking';
  const available = useAll
    ? Object.keys(MODELS).some(mid => !['offline', 'checking'].includes(workerStatus[mid]))
    : !['offline', 'checking'].includes(workerStatus[selectedModel]);
  $('btn-synth').disabled = !hasText || isGenerating || isComparing || !available;
  $('synth-label').textContent = checking ? t('synth.checking') :
    !available ? t('synth.unavailable') :
    isGenerating || isComparing ? t('synth.running') :
    useAll ? t('synth.compare') :
    speakVariant !== 'tashkeel' ? t('synth.run') :
    tashkeelMarks === 'shadda' ? t('synth.runShadda') : t('synth.runTashkeel');
  updateCompareLabel();
}

// ── Poll worker health ────────────────────────────────────────
function renderWorkerStatus() {
  renderStatusBadges();
  renderModelCards();
  renderCompareChecks();
  updateSynthBtn();
}

async function pollStatus() {
  if (statusPollInFlight) return;
  statusPollInFlight = true;
  let timeout = null;
  try {
    // Promise.race keeps the check bounded even in browsers without AbortController.
    // Abort the underlying request too when that API is available.
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const request = fetch(appUrl('api/status'), {
      cache: 'no-store',
      ...(controller ? { signal: controller.signal } : {}),
    });
    const deadline = new Promise((_, reject) => {
      timeout = setTimeout(() => {
        if (controller) controller.abort();
        reject(new Error('Status request timed out'));
      }, 15_000);
    });
    const r = await Promise.race([request, deadline]);
    if (!r.ok) throw new Error(`Status request failed: HTTP ${r.status}`);
    const data = await r.json();
    if (!data || typeof data !== 'object') throw new Error('Invalid status response');
    for (const mid of Object.keys(MODELS)) {
      const info = data[mid];
      if (!info || typeof info !== 'object') {
        workerStatus[mid] = 'offline';
        continue;
      }
      const want = (MODELS[mid].fixedParams || {}).variant || '';
      if (info.status === 'offline') {
        workerStatus[mid] = 'offline';
      } else if (want && info.variants && !(want in info.variants)) {
        // Worker is up but this variant's weights are missing server-side.
        workerStatus[mid] = 'offline';
      } else if (info.model_loaded && (!want ||
                 (Array.isArray(info.loaded_variants) && info.loaded_variants.includes(want)) ||
                 info.loaded_variant === want)) {
        workerStatus[mid] = 'online';
      } else {
        // Worker up; this variant loads on demand (or another variant currently holds the RAM).
        workerStatus[mid] = 'loading';
      }
    }
    syncVoicesWithStatus(data);
    asrOnline = Boolean(data.transcribe && data.transcribe.status !== 'offline');
  } catch {
    // A failed gateway request is a completed check, not an indefinitely pending one.
    for (const mid of Object.keys(MODELS)) workerStatus[mid] = 'offline';
  } finally {
    clearTimeout(timeout);
    statusPollInFlight = false;
    renderWorkerStatus();
  }
}

function startStatusPolling() {
  void pollStatus();
  if (!statusPollTimer) statusPollTimer = setInterval(pollStatus, 10_000);

  // Never leave the initial state spinning indefinitely, even if a browser extension,
  // compatibility issue, or a later optional UI initializer interrupts normal startup.
  setTimeout(() => {
    let changed = false;
    for (const mid of Object.keys(MODELS)) {
      if (workerStatus[mid] === 'checking') {
        workerStatus[mid] = 'offline';
        changed = true;
      }
    }
    if (changed) renderWorkerStatus();
  }, 16_000);
}

// ── Current "instruct" (voice description / prompt text) ──────
// The instruction for both OmniVoice variants is the speaker voice description.
function currentInstruct() {
  const v = paramValues[selectedModel];
  return v ? (v.speaker || '').trim() : '';
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
    fd.append('model_instruct_override', ov.instruct);
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
  if ($('use-all-models') && $('use-all-models').checked) {
    return compareModels();
  }
  if (isGenerating) return;
  const original = $('text-input').value.trim();
  if (!original) return;

  isGenerating = true;
  updateSynthBtn();
  $('synth-progress').classList.remove('hidden');
  $('progress-hint').textContent = t('synth.running');

  let hintTimer = null;
  try {
    const { text, variant } = await textToSpeak(original);   // may run the tashkeel agent first
    $('progress-hint').textContent = t('synth.running');
    if (workerStatus[selectedModel] === 'loading') {
      hintTimer = setTimeout(() => {
        $('progress-hint').textContent = t('synth.loadingModel');
      }, 3000);
    }

    const fd = buildFormDataForModel(selectedModel, text, true);
    const r  = await fetch(appUrl(`api/${selectedModel}/synthesize`), { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await errorText(r));

    const result = await r.json();
    const audioUrl = modelAudioUrl(selectedModel, result.filename);
    const options = optionSummary(selectedModel, true);

    await loadPlayer(audioUrl, { ...result, model: selectedModel, options, variant }, text);
    addToHistory({
      ...result, model: selectedModel,   // interface id, not the worker's "omnivoice"
      text, variant, original, url: audioUrl, options, timestamp: Date.now(),
      instruct: currentInstruct(),
      params: { ...paramValues[selectedModel] },
    });
    showToast(t('synth.done'), 'success');

  } catch (e) {
    showToast(`${t('misc.error')}: ${e.message}`, 'error', 6000);
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
    <span class="rtf-badge">${formatSeconds(meta.elapsed_s)} ${t('badge.generated')}</span>
  `;

  const insights = $('player-insights');
  if (insights) {
    const options = meta.options || optionSummary(meta.model, false);
    const variant = meta.variant || (hasTashkeel(text) ? 'tashkeel' : 'original');
    insights.innerHTML = `
      ${text ? `<div class="player-text">${variantBadgeHtml(variant)}${runTextHtml(text)}</div>` : ''}
      ${metricGridHtml(meta)}
      ${optionChipsHtml(options)}
    `;
  }

  // Download
  const dl = $('btn-dl');
  dl.href = url;
  dl.download = meta.filename;
  const dlMp3 = $('btn-dl-mp3');
  dlMp3.href = mp3Url(url);
  dlMp3.download = mp3Name(meta.filename);

  // Player button color
  const playBtn = $('btn-play');
  playBtn.className = `btn-play ${meta.model}`;

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
    const color = mid === 'omnivoice_base' ? '#3fb950' : mid === 'omnivoice_najdi' ? '#bc8cff' : '#58a6ff';
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
    historyItems = Array.isArray(saved) ? saved.filter(i => MODELS[i.model]).map(item => ({
      ...item,
      // Repair URLs saved by older builds that pointed at the domain-root /audio route.
      url: item.filename ? modelAudioUrl(item.model, item.filename) : item.url,
    })) : [];
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
  btn.textContent = historyCollapsed ? t('hist.expand') : t('hist.collapse');
  btn.title = historyCollapsed ? t('hist.expandTitle') : t('hist.collapseTitle');
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
    const fullText = item.text || item.filename || '';
    const variant = item.variant || (hasTashkeel(item.text) ? 'tashkeel' : 'original');
    const params = item.params || {};
    const voiceName = item.voice_label || params.voice_label || voiceNameFor(item.voice || params.voice);
    const ago = formatAgo(item.timestamp);
    const instruct = (item.instruct || '').trim();
    const instructRow = instruct
      ? `<div class="hi-instruct" title="${escapeAttr(instruct)}">🎙 ${escapeHtml(instruct.slice(0, 50))}</div>`
      : '';
    const metaBits = [
      `${formatSeconds(item.elapsed_s)} ${t('badge.generated')}`,
      `${formatSeconds(item.duration_s)} ${t('badge.audio')}`,
      `RTF ${formatRtf(item.rtf)}`,
      ago,
    ].filter(v => v && !v.startsWith('—'));
    el.innerHTML = `
      <div class="hi-badge"><span class="model-badge ${item.model}">${(MODELS[item.model] && MODELS[item.model].icon) || ''}</span></div>
      <div class="hi-info">
        <div class="hi-tags">
          ${variantBadgeHtml(variant)}
          ${voiceName ? `<span class="hi-voice">🎙 ${escapeHtml(voiceName)}</span>` : ''}
        </div>
        <div class="hi-text" dir="auto" title="${escapeAttr(t('hist.textToggle'))}">${escapeHtml(fullText)}</div>
        ${instructRow}
        <div class="hi-meta">${escapeHtml(metaBits.join(' · '))}</div>
      </div>
      <div class="hi-actions">
        <button class="hi-btn play" title="${t('hist.play')}">▶</button>
        <a class="hi-btn dl" href="${item.url}" download="${item.filename}" title="${t('hist.download')}">⬇</a>
        <a class="hi-btn dl" href="${mp3Url(item.url)}" download="${mp3Name(item.filename)}" title="${t('hist.downloadMp3')}">MP3</a>
      </div>
    `;
    el.querySelector('.hi-btn.play').addEventListener('click', e => {
      e.stopPropagation();
      playHistoryItem(item);
    });
    // Long texts are clamped; clicking the text opens it instead of replaying the clip.
    el.querySelector('.hi-text').addEventListener('click', e => {
      e.stopPropagation();
      e.currentTarget.classList.toggle('expanded');
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
  if (diff < 60)   return `${diff}${t('ago.s')}`;
  if (diff < 3600) return `${Math.floor(diff/60)}${t('ago.m')}`;
  if (diff < 86400)return `${Math.floor(diff/3600)}${t('ago.h')}`;
  return `${Math.floor(diff/86400)}${t('ago.d')}`;
}

// ── Load server history on startup ────────────────────────────
async function loadServerHistory() {
  const existing = new Set(historyItems.map(i => i.filename));
  for (const mid of Object.keys(MODELS)) {
    try {
      const r = await fetch(appUrl(`api/${mid}/history?limit=30`));
      if (!r.ok) continue;
      const files = await r.json();
      for (const f of files) {
        // All interface models share one output dir; assign each clip to the card whose
        // variant generated it. Clips predating variant tracking ran the since-removed
        // Saudi-HQ fine-tune, so they match no card.
        const variant = (f.params && f.params.variant) || 'finetuned';
        if (variant !== MODELS[mid].fixedParams.variant) continue;
        if (!existing.has(f.filename)) {
          historyItems.push({
            filename:   f.filename,
            model:      mid,
            url:        modelAudioUrl(mid, f.filename),
            text:       f.text || '',
            instruct:   f.instruct || '',
            params:     f.params || null,
            voice:      (f.params && f.params.voice) || '',
            voice_label: (f.params && f.params.voice_label) || '',
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
// One compare item is one model speaking one version of the text. Runs saved before the
// tashkeel mode existed carry neither key nor text: they were one original per model.
const itemKey = item => item.key || item.mid;
const itemText = (run, item) => item.text || run.text || '';
const itemVariant = item => item.variant || 'original';
const itemName = item => `${MODELS[item.mid].name}${item.variant ? ` · ${variantLabel(item.variant)}` : ''}`;

function runTextHtml(text) {
  return `<div class="run-text" dir="auto">${escapeHtml(text)}</div>`;
}

function miniTitleHtml(item) {
  const m = MODELS[item.mid];
  return `
    <div class="mini-player-title">
      <span>${m.icon} ${escapeHtml(m.name)} ${variantBadgeHtml(itemVariant(item))}</span>
      <small>${escapeHtml(m.compareNote)}</small>
    </div>
  `;
}

// Final content for one compare mini-player — used both live and when restoring a saved run.
function miniPlayerHtml(item, run) {
  const mid = item.mid;
  const options = item.options || optionSummary(mid, false);
  const text = itemText(run, item);
  if (item.error) {
    return `
      ${miniTitleHtml(item)}
      ${runTextHtml(text)}
      <div class="mini-player-meta error">${t('misc.error')}: ${escapeHtml(String(item.error).slice(0, 160))}</div>
      <button class="mini-retry" data-run-id="${escapeAttr(run.id)}" data-key="${escapeAttr(itemKey(item))}" type="button">${t('cmp.retry')}</button>
      ${optionChipsHtml(options)}
    `;
  }
  const url = item.result && item.result.filename
    ? modelAudioUrl(mid, item.result.filename)
    : item.url;
  // The text is already shown; repeat what reached the model only when it differs.
  const result = item.result || {};
  const sent = result.model_instruct || (result.model_input && result.model_input !== text)
    ? sentInputHtml(result) : '';
  return `
    ${miniTitleHtml(item)}
    ${runTextHtml(text)}
    <audio controls preload="metadata" src="${escapeHtml(url)}"></audio>
    ${metricGridHtml(result)}
    ${run.mode === 'tashkeel' ? '' : `<div class="mini-player-meta">${escapeHtml(MODELS[mid].role)}</div>`}
    ${optionChipsHtml(options)}
    ${sent}
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
      <strong>${row ? escapeHtml(itemName(row)) : '—'}</strong>
      <small>${escapeHtml(value || '—')}</small>
    </div>
  `;

  const summary = document.createElement('div');
  summary.className = 'compare-summary';
  summary.innerHTML = `
    <div class="summary-title">${t('cmp.summary')}</div>
    <div class="summary-grid">
      ${item(t('cmp.fastest'), fastest, fastest ? formatSeconds(fastest.result.elapsed_s) : '')}
      ${item(t('cmp.bestRtf'), bestRtf, bestRtf ? `${formatRtf(bestRtf.result.rtf)} · ${rtfProfile(bestRtf.result.rtf).label}` : '')}
      ${item(t('cmp.highestRate'), highestRate, highestRate ? formatSampleRate(highestRate.result.sample_rate) : '')}
      <div class="summary-item">
        <span>${t('cmp.count')}</span>
        <strong>${ok.length}/${results.length}</strong>
        <small>${results.some(r => r.error) ? t('cmp.hasErrors') : t('cmp.allDone')}</small>
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
    compareRuns = Array.isArray(arr) ? arr
      .filter(run => run && typeof run === 'object' && Array.isArray(run.items))
      .map(run => ({
        ...run,
        id: String(run.id || `c${run.timestamp || Date.now()}`),
        text: String(run.text || ''),
        timestamp: Number(run.timestamp) || Date.now(),
        items: run.items.filter(item => item && typeof item === 'object' && MODELS[item.mid]),
      }))
      .filter(run => run.items.length) : [];
  } catch { compareRuns = []; }
  // One-time migration of the old single-slot run into the new list.
  if (!compareRuns.length) {
    try {
      const old = JSON.parse(localStorage.getItem(COMPARE_KEY) || 'null');
      if (old && Array.isArray(old.items) && old.items.length) {
        const items = old.items.filter(item => item && typeof item === 'object' && MODELS[item.mid]);
        if (!items.length) throw new Error('Legacy comparison data is invalid');
        compareRuns = [{ id: `c${old.timestamp || Date.now()}`, text: old.text || '',
                         timestamp: old.timestamp || Date.now(), items }];
        persistCompareRuns();
      }
    } catch { /* ignore */ }
    try { localStorage.removeItem(COMPARE_KEY); } catch { /* ignore */ }
  }
  // A run interrupted by a reload may have left items mid-generation — surface them as
  // retryable errors instead of a stuck spinner.
  for (const run of compareRuns) {
    for (const item of run.items || []) {
      if (item.pending) { delete item.pending; if (!item.result) item.error = item.error || t('cmp.incomplete'); }
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
  if (!confirm(t('cmp.confirmClear'))) return;
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
    mini.id = `mini-${run.id}-${itemKey(item)}`;
    mini.innerHTML = item.pending
      ? `${miniTitleHtml(item)}${runTextHtml(itemText(run, item))}<div class="mini-spinner">${t('cmp.waiting')}</div>${optionChipsHtml(item.options || optionSummary(item.mid, false))}`
      : miniPlayerHtml(item, run);
    container.appendChild(mini);
  }
  renderCompareSummary(container, (run.items || []).filter(i => !i.pending && i.result));
}

// Replace one mini-player's content in place (used during live generation + retry).
function setMiniHtml(runId, key, html) {
  const mini = $(`mini-${runId}-${key}`);
  if (mini) mini.innerHTML = html;
}

// Rebuild a run's "best of" summary in place without touching its players.
function refreshRunSummary(run) {
  const first = (run.items || [])[0];
  const mini = first && $(`mini-${run.id}-${itemKey(first)}`);
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

// Re-run a single failed (or any) item in a comparison, reusing its text + captured params.
async function retryCompareItem(runId, key) {
  if (isComparing) { showToast(t('cmp.busy'), 'warn'); return; }
  const run = compareRuns.find(r => r.id === runId);
  if (!run) { showToast(t('cmp.notFound'), 'error'); return; }
  const idx = (run.items || []).findIndex(i => itemKey(i) === key);
  if (idx === -1) return;

  const prev = run.items[idx];
  const mid = prev.mid;
  const text = itemText(run, prev);
  const options = prev.options || optionSummary(mid, false);
  const base = { key: itemKey(prev), mid, variant: itemVariant(prev), text, options, params: prev.params };
  expandedCompareRuns.add(runId);   // make sure the run is visible while it retries
  setMiniHtml(runId, key, `${miniTitleHtml(prev)}${runTextHtml(text)}<div class="mini-spinner">${t('cmp.retrying')}</div>${optionChipsHtml(options)}`);

  let item;
  try {
    const fd = buildFormDataForModel(mid, text, false, prev.params || null);
    const r = await fetch(appUrl(`api/${mid}/synthesize`), { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await errorText(r));
    const result = await r.json();
    const url = modelAudioUrl(mid, result.filename);
    addToHistory({ ...result, model: mid, text, variant: base.variant, original: run.text, url, options, timestamp: Date.now() });
    item = { ...base, result, url };
    showToast(t('cmp.retried'), 'success');
  } catch (e) {
    item = { ...base, error: e.message };
    showToast(t('cmp.retryFailed', { err: String(e.message).slice(0, 80) }), 'error', 5000);
  }

  run.items[idx] = item;
  persistCompareRuns();
  setMiniHtml(runId, key, miniPlayerHtml(item, run));
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
    toggleAll.textContent = allOpen ? t('cmp.collapseAll') : t('cmp.expandAll');
    toggleAll.dataset.expand = allOpen ? '0' : '1';
  }

  list.innerHTML = '';
  for (const run of compareRuns) {
    const expanded = expandedCompareRuns.has(run.id);
    const icons = [...new Set((run.items || []).map(i => (MODELS[i.mid] || {}).icon || ''))].join(' ');
    const n = (run.items || []).length;
    const errs = (run.items || []).filter(i => i.error).length;
    const snippet = run.text || '—';
    const mode = run.mode === 'tashkeel' ? t('cmp.modeTashkeel') : t('cmp.modeModels');
    const meta = `${mode} · ${icons} · ${n} ${t('cmp.clips')}${errs ? ` · ${errs} ${t('cmp.errors')}` : ''} · ${formatAgo(run.timestamp)}`;

    const itemEl = document.createElement('div');
    itemEl.className = `saved-compare-item ${expanded ? 'expanded' : ''}`;
    itemEl.dataset.id = run.id;

    const head = document.createElement('div');
    head.className = 'sc-head';
    head.innerHTML = `
      <span class="sc-caret">${expanded ? '▾' : '▸'}</span>
      <div class="sc-info">
        <div class="sc-snippet" dir="auto">${escapeHtml(snippet)}</div>
        <div class="sc-meta">${escapeHtml(meta)}</div>
      </div>
      <div class="sc-actions">
        <button class="hi-btn sc-del" title="${t('hist.delete')}">🗑</button>
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

// The items one comparison generates, or null when it cannot start (the reason is shown).
async function compareItems(original) {
  if (compareMode === 'tashkeel') {
    const mid = selectedModel;
    if (['offline', 'checking'].includes(workerStatus[mid])) {
      showToast(t('cmp.modelOffline', { model: MODELS[mid].name }), 'warn');
      return null;
    }
    $('progress-hint').textContent = t('tk.running');
    const tk = await ensureTashkeel(original);
    if (!tk) return null;                       // makeTashkeel already said why
    return [
      { key: `${mid}:original`, mid, variant: 'original', text: original },
      { key: `${mid}:tashkeel`, mid, variant: markedVariant(), text: tk },
    ];
  }
  const mids = Object.keys(MODELS).filter(mid => workerStatus[mid] !== 'offline');
  if (!mids.length) { showToast(t('cmp.needModel'), 'warn'); return null; }
  const { text, variant } = await textToSpeak(original);
  return mids.map(mid => ({ key: mid, mid, variant, text }));
}

async function compareModels() {
  if (isComparing) return;
  const original = $('text-input').value.trim();
  if (!original) { showToast(t('synth.needText'), 'warn'); return; }

  isComparing = true;
  const btn = $('btn-compare');
  if (btn) btn.disabled = true;
  updateSynthBtn();
  $('synth-progress').classList.remove('hidden');

  let run = null;
  try {
    const items = await compareItems(original);
    if (!items) return;
    $('progress-hint').textContent = t('cmp.preparing', { n: items.length });

    // Create the run up front and show it expanded at the top of the library, so the live
    // generation streams into the same card the user will keep and compare against later.
    // params snapshot per item lets a later retry reproduce these exact inputs.
    run = {
      id: `c${Date.now()}`,
      text: original,
      mode: compareMode,
      timestamp: Date.now(),
      items: items.map(it => ({ ...it, pending: true, options: optionSummary(it.mid, false),
                                params: { ...paramValues[it.mid] } })),
    };
    currentCompareRunId = run.id;
    expandedCompareRuns.add(run.id);
    addCompareRun(run);   // unshift + persist + renderCompareLibrary → renders the pending card
    const compareCard = $('saved-compare-card');
    if (compareCard && typeof compareCard.scrollIntoView === 'function') {
      compareCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    for (let i = 0; i < run.items.length; i++) {
      const pending = run.items[i];
      const key = itemKey(pending);
      const progress = t('cmp.progress', { i: i + 1, n: run.items.length });
      if ($('compare-label')) $('compare-label').textContent = progress;
      $('synth-label').textContent = progress;
      $('progress-hint').textContent = t('cmp.progressHint', { p: progress });
      setMiniHtml(run.id, key, `${miniTitleHtml(pending)}${runTextHtml(pending.text)}<div class="mini-spinner">${t('cmp.generating')}</div>${optionChipsHtml(pending.options)}`);

      const base = { key, mid: pending.mid, variant: pending.variant, text: pending.text,
                     options: pending.options, params: pending.params };
      let item;
      try {
        const fd = buildFormDataForModel(pending.mid, pending.text, false);
        const r = await fetch(appUrl(`api/${pending.mid}/synthesize`), { method: 'POST', body: fd });
        if (!r.ok) throw new Error(await errorText(r));
        const result = await r.json();
        const url = modelAudioUrl(pending.mid, result.filename);
        addToHistory({ ...result, model: pending.mid, text: pending.text, variant: pending.variant,
                       original, url, options: pending.options, timestamp: Date.now() });
        item = { ...base, result, url };
      } catch (e) {
        item = { ...base, error: e.message || String(e) };
      }

      run.items[i] = item;
      persistCompareRuns();
      setMiniHtml(run.id, key, miniPlayerHtml(item, run));
      refreshRunSummary(run);
    }

    const hadErr = run.items.some(r => r.error);
    showToast(hadErr ? t('cmp.doneErr') : t('cmp.done'), hadErr ? 'warn' : 'success');
  } catch (e) {
    const message = String(e.message || e).slice(0, 120);
    if (run) {
      for (const item of run.items) {
        if (item.pending) {
          delete item.pending;
          item.error = message;
        }
      }
      try {
        persistCompareRuns();
        renderCompareLibrary();
      } catch { /* the progress controls are still reset below */ }
    }
    showToast(t('cmp.startFailed', { err: message }), 'error', 6000);
  } finally {
    isComparing = false;
    currentCompareRunId = null;
    $('synth-progress').classList.add('hidden');
    updateCompareMode();
    updateSynthBtn();
  }
}

// ── Accordion toggle ──────────────────────────────────────────
function setupAccordions() {
  $$('.acc-header').forEach(btn => {
    btn.addEventListener('click', () => {
      const section = btn.closest('.accordion');
      setAccordionOpen(section.id, $(btn.dataset.target).classList.contains('collapsed'));
    });
  });
}

function setAccordionOpen(sectionId, open) {
  const section = $(sectionId);
  if (!section) return;
  const body = section.querySelector('.acc-body');
  body.classList.toggle('collapsed', !open);
  section.classList.toggle('open', open);
}

// ── Clear history ─────────────────────────────────────────────
function clearHistory() {
  if (!confirm(t('hist.confirmClear'))) return;
  historyItems = [];
  saveHistory();
  renderHistory();
}

function setupPrimaryActions() {
  const textInput = $('text-input');
  if (!textInput || textInput.dataset.primaryActionsBound === '1') return;
  textInput.dataset.primaryActionsBound = '1';

  textInput.addEventListener('input', () => {
    updateCharCount();
    updateSynthBtn();
  });

  const synthBtn = $('btn-synth');
  if (synthBtn) synthBtn.addEventListener('click', synthesize);

  const compareBtn = $('btn-compare');
  if (compareBtn) compareBtn.addEventListener('click', () => compareModels());

  const compareToggle = $('use-all-models');
  if (compareToggle) {
    compareToggle.addEventListener('change', () => {
      updateCompareMode();
      updateSynthBtn();
    });
  }

  const clearBtn = $('btn-clear-text');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      textInput.value = '';
      updateCharCount();
      updateSynthBtn();
    });
  }

  updateCompareMode();
}

// ── Init ──────────────────────────────────────────────────────
// Panels built imperatively hold text that `I18N.apply` cannot reach — it only rewrites
// nodes carrying data-i18n. Re-render them whenever the language flips.
function setupLanguageToggle() {
  document.addEventListener('languagechange', () => {
    try {
      renderModelCards();
      renderStatusBadges();
      renderVoicePicker();
      renderCompareChecks();
      renderHistory($('history-filter') ? $('history-filter').value : 'all');
      renderCompareLibrary();
      updateSynthBtn();
      updateCompareLabel();
    } catch (e) {
      console.error('Re-render after language change failed', e);
    }
  });
}

function init() {
  // Paint the stored language before anything renders, so the first frame is correct.
  I18N.apply();
  setupLanguageToggle();

  initParamValues();
  loadHistory();
  loadHistoryCollapsed();

  renderModelCards();
  renderStatusBadges();

  // Start health synchronization before initializing optional controls. A problem in an
  // unrelated panel must not prevent the model cards from leaving their initial state.
  startStatusPolling();

  // Primary actions must remain usable even if optional history/local-storage restoration
  // encounters stale data from an older frontend version.
  setupPrimaryActions();

  // Transcription is optional too, but it is wired before the restoration block so a
  // stale-localStorage failure there cannot leave the transcribe button dead.
  setupTranscription();
  setupTashkeel();
  setupCompareModes();
  setupVoiceLibrary();

  try {
    renderVoicePicker();
    renderCompareChecks();
    renderHistory();
    loadCompareRuns();
    if (compareRuns[0]) expandedCompareRuns.add(compareRuns[0].id);
    renderCompareLibrary();
    setupAudioEvents();
  } catch (e) {
    console.error('Optional UI initialization failed', e);
    showToast(t('misc.bootWarn'), 'warn', 6000);
  }

  // Clear history
  $('btn-clear-history').addEventListener('click', clearHistory);

  // Collapse / expand history
  $('btn-toggle-history').addEventListener('click', toggleHistoryCollapsed);

  if ($('btn-clear-compares')) $('btn-clear-compares').addEventListener('click', clearCompareRuns);

  if ($('btn-toggle-compares')) {
    $('btn-toggle-compares').addEventListener('click', e => {
      setAllCompareRunsExpanded(e.currentTarget.dataset.expand === '1');
    });
  }

  // History filter
  $('history-filter').addEventListener('change', () => renderHistory());

  if ($('saved-compare-list')) {
    $('saved-compare-list').addEventListener('click', e => {
      const btn = e.target.closest('.mini-retry');
      if (btn) { e.stopPropagation(); retryCompareItem(btn.dataset.runId, btn.dataset.key || btn.dataset.mid); }
    });
  }

  // Load server-side history after status check
  setTimeout(loadServerHistory, 1500);
}

document.addEventListener('DOMContentLoaded', init);
