'use strict';

// ── Model definitions ────────────────────────────────────────
const MODELS = {
  fish: {
    id: 'fish',
    name: 'Fish S2 Pro',
    icon: '🐟',
    specs: '5B · 44kHz',
    params: [
      { id: 'temperature', label: 'Temperature', type: 'range', min: 0.1, max: 2.0, step: 0.05, default: 0.7 },
      { id: 'top_p',       label: 'Top-P',        type: 'range', min: 0.0, max: 1.0, step: 0.05, default: 0.8 },
      { id: 'top_k',       label: 'Top-K',        type: 'range', min: 1,   max: 100, step: 1,    default: 30  },
      { id: 'max_tokens',  label: 'Max Tokens',   type: 'range', min: 256, max: 4096,step: 256,  default: 2048},
    ],
    emotionTags: ['[excited]', '[whisper]', '[laugh]', '[sad]', '[news]'],
    cloneFields: ['ref_audio', 'ref_text'],
    formFields: { reference_audio: 'ref_audio', reference_text: 'ref_text' },
  },
  omnivoice: {
    id: 'omnivoice',
    name: 'OmniVoice',
    icon: '🌐',
    specs: '0.6B · 24kHz · 646 lang',
    params: [
      { id: 'speaker', label: 'Voice Description (optional)', type: 'text',
        placeholder: 'e.g. A professional male Arabic news anchor', default: '' },
    ],
    emotionTags: ['[laughter]', '[applause]'],
    cloneFields: ['ref_audio', 'ref_text'],
    formFields: { ref_audio: 'ref_audio', ref_text: 'ref_text' },
  },
  voxcpm2: {
    id: 'voxcpm2',
    name: 'VoxCPM2',
    icon: '🔊',
    specs: '2B · 48kHz · Diffusion',
    params: [
      { id: 'cfg_value',           label: 'CFG Value',        type: 'range',  min: 1.0, max: 5.0, step: 0.1, default: 2.0 },
      { id: 'inference_timesteps', label: 'Timesteps',        type: 'select', options: [5, 10, 20], default: 10 },
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

const SAMPLE_SENTENCES = [
  'مرحباً، كيف حالك؟',
  'أهلاً وسهلاً، يسعدنا تواجدكم معنا.',
  'أعلنت وزارة الصحة عن إطلاق حملة تطعيم وطنية شاملة.',
  'الذكاء الاصطناعي يُحدث ثورة في تحويل النص إلى كلام text-to-speech.',
  'اللغة العربية لغة سامية غنية بمفرداتها وتراثها الأدبي.',
];

// ── State ─────────────────────────────────────────────────────
let selectedModel = 'fish';
let workerStatus  = { fish: 'offline', omnivoice: 'offline', voxcpm2: 'offline' };
let currentAudioUrl = null;
let isGenerating  = false;
let audioCtx      = null;
let paramValues   = {};  // { fish: {temperature: 0.7, ...}, ... }
let cloneFiles    = {};  // { ref_audio: File|null, ref_text: '', ... }

// ── DOM helpers ───────────────────────────────────────────────
const $  = id => document.getElementById(id);
const $$ = sel => document.querySelectorAll(sel);

function formatTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, '0')}`;
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
    paramValues[mid] = {};
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
    const card = document.createElement('div');
    card.className = `model-card ${m.id} ${selectedModel === m.id ? 'active' : ''} ${st === 'offline' ? 'offline' : ''}`;
    card.dataset.model = m.id;
    card.innerHTML = `
      <div class="mc-icon">${m.icon}</div>
      <div class="mc-name">${m.name}</div>
      <div class="mc-specs">${m.specs}</div>
      <div class="mc-status ${st}">${st === 'online' ? '● متاح' : st === 'loading' ? '● تحميل' : '● غير متاح'}</div>
    `;
    card.addEventListener('click', () => selectModel(m.id));
    container.appendChild(card);
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
function renderParams() {
  const body = $('params-body');
  const model = MODELS[selectedModel];
  if (!model.params.length) {
    body.innerHTML = '<p style="font-size:.75rem;color:var(--txt3)">لا توجد معاملات إضافية.</p>';
    return;
  }
  body.innerHTML = '';
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
      `;
      body.appendChild(row);
      row.querySelector('input').addEventListener('input', e => {
        const v = parseFloat(e.target.value);
        paramValues[selectedModel][p.id] = v;
        $(`v-${p.id}`).textContent = v;
      });

    } else if (p.type === 'select') {
      row.className = 'param-row';
      const opts = p.options.map(o => `<option value="${o}" ${o == val ? 'selected' : ''}>${o}</option>`).join('');
      row.innerHTML = `
        <label class="param-label" for="p-${p.id}">${p.label}</label>
        <select class="param-select" id="p-${p.id}">${opts}</select>
      `;
      body.appendChild(row);
      row.querySelector('select').addEventListener('change', e => {
        paramValues[selectedModel][p.id] = parseInt(e.target.value);
      });

    } else if (p.type === 'text') {
      const wrap = document.createElement('div');
      wrap.style.display = 'flex';
      wrap.style.flexDirection = 'column';
      wrap.style.gap = '4px';
      wrap.innerHTML = `
        <label class="param-label" style="padding-bottom:0" for="p-${p.id}">${p.label}</label>
        <input class="param-text" type="text" id="p-${p.id}"
          placeholder="${p.placeholder || ''}" value="${val}">
      `;
      body.appendChild(wrap);
      wrap.querySelector('input').addEventListener('input', e => {
        paramValues[selectedModel][p.id] = e.target.value;
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

  if (model.id === 'fish' || model.id === 'omnivoice') {
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
    const checked = workerStatus[m.id] === 'online' ? 'checked' : '';
    const disabled = workerStatus[m.id] !== 'online' ? 'disabled' : '';
    label.innerHTML = `
      <input type="checkbox" value="${m.id}" ${checked} ${disabled}>
      ${m.icon} ${m.name}
    `;
    container.appendChild(label);
  }
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
    });
    container.appendChild(chip);
  }
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

// ── Build FormData for synthesis ──────────────────────────────
function buildFormData() {
  const fd   = new FormData();
  const text = $('text-input').value.trim();
  fd.append('text', text);

  // Model-specific params
  const vals = paramValues[selectedModel];
  for (const [k, v] of Object.entries(vals)) {
    fd.append(k, v);
  }

  // Clone files/text
  const model = MODELS[selectedModel];
  for (const [formKey, stateKey] of Object.entries(model.formFields || {})) {
    const val = cloneFiles[stateKey];
    if (val instanceof File)   fd.append(formKey, val, val.name);
    else if (typeof val === 'string' && val.trim()) fd.append(formKey, val.trim());
  }

  return fd;
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

    await loadPlayer(audioUrl, result, text);
    addToHistory({ ...result, text, url: audioUrl, timestamp: Date.now() });
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
  badges.innerHTML = `
    <span class="model-badge ${meta.model}">${MODELS[meta.model]?.name || meta.model}</span>
    <span class="rtf-badge">${meta.elapsed_s}s · RTF ${meta.rtf}</span>
    <span class="rtf-badge">${meta.duration_s}s audio</span>
  `;

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
  drawWaveform(url);
}

// ── Waveform drawing ──────────────────────────────────────────
async function drawWaveform(url) {
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
    const color = selectedModel === 'fish' ? '#f0883e' :
                  selectedModel === 'voxcpm2' ? '#3fb950' : '#58a6ff';
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
let historyItems = [];

function loadHistory() {
  try {
    historyItems = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
  } catch { historyItems = []; }
}

function saveHistory() {
  // Keep last 200 items
  const trimmed = historyItems.slice(0, 200);
  localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed));
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
    el.innerHTML = `
      <div class="hi-badge"><span class="model-badge ${item.model}">${MODELS[item.model]?.icon || ''}</span></div>
      <div class="hi-info">
        <div class="hi-filename">${textSnippet}</div>
        <div class="hi-meta">${item.duration_s}s · RTF ${item.rtf} · ${ago}</div>
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
            text:       '',
            duration_s: 0,
            rtf:        0,
            elapsed_s:  0,
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

// ── Compare all models ────────────────────────────────────────
async function compareModels() {
  const text = $('text-input').value.trim();
  if (!text) { showToast('أدخل نصاً أولاً', 'warn'); return; }

  const selected = Array.from($$('#compare-checks input:checked')).map(e => e.value);
  if (!selected.length) { showToast('اختر نموذجاً واحداً على الأقل', 'warn'); return; }

  $('compare-results').classList.remove('hidden');
  const grid = $('compare-grid');
  grid.innerHTML = '';

  // Create mini-player placeholders
  const players = {};
  for (const mid of selected) {
    const mini = document.createElement('div');
    mini.className = `mini-player ${mid}`;
    mini.id = `mini-${mid}`;
    mini.innerHTML = `
      <div class="mini-player-title">${MODELS[mid].icon} ${MODELS[mid].name}</div>
      <div class="mini-spinner">جاري التوليد…</div>
    `;
    grid.appendChild(mini);
    players[mid] = mini;
  }

  // Run all in parallel
  const promises = selected.map(async mid => {
    try {
      const fd = new FormData();
      fd.append('text', text);
      const vals = paramValues[mid];
      for (const [k, v] of Object.entries(vals)) fd.append(k, v);

      const r = await fetch(`/api/${mid}/synthesize`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const result = await r.json();
      const url = `/audio/${mid}/${result.filename}`;
      addToHistory({ ...result, text, url, timestamp: Date.now() });

      players[mid].innerHTML = `
        <div class="mini-player-title">${MODELS[mid].icon} ${MODELS[mid].name}</div>
        <audio controls preload="auto" src="${url}"></audio>
        <div class="mini-player-meta">${result.duration_s}s · RTF ${result.rtf} · ${result.elapsed_s}s</div>
      `;
    } catch (e) {
      players[mid].innerHTML = `
        <div class="mini-player-title">${MODELS[mid].icon} ${MODELS[mid].name}</div>
        <div class="mini-player-meta" style="color:var(--red)">خطأ: ${e.message.slice(0,80)}</div>
      `;
    }
  });

  await Promise.all(promises);
  showToast('اكتملت المقارنة', 'success');
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

  renderModelCards();
  renderStatusBadges();
  renderParams();
  renderTags();
  renderClonePanel();
  renderCompareChecks();
  renderSampleChips();
  renderHistory();
  setupAccordions();
  setupAudioEvents();

  // Text input events
  $('text-input').addEventListener('input', () => {
    updateCharCount();
    updateSynthBtn();
  });

  // Synth button
  $('btn-synth').addEventListener('click', synthesize);

  // Clear text
  $('btn-clear-text').addEventListener('click', () => {
    $('text-input').value = '';
    updateCharCount();
    updateSynthBtn();
  });

  // Clear history
  $('btn-clear-history').addEventListener('click', clearHistory);

  // History filter
  $('history-filter').addEventListener('change', () => renderHistory());

  // Compare
  $('btn-compare').addEventListener('click', compareModels);

  // Initial status poll + periodic refresh
  pollStatus();
  setInterval(pollStatus, 10_000);

  // Load server-side history after status check
  setTimeout(loadServerHistory, 1500);
}

document.addEventListener('DOMContentLoaded', init);
