'use strict';

// ── Interface language ────────────────────────────────────────
// One dictionary drives both pages. Markup carries `data-i18n` keys rather than text,
// so switching language rewrites the DOM in place — no reload, no second copy of the
// HTML to keep in sync.
//
// Direction flips with the language: Arabic is RTL, English LTR. Everything else in
// the stack (model ids, the audio itself, the `language` field sent to the ASR worker)
// is untouched by this — it is presentation only.
const I18N = (() => {
  const STORE_KEY = 'ui-lang';

  const STRINGS = {
    // ── Chrome ────────────────────────────────────────────────
    'brand.title':        { ar: 'استوديو تحويل النص إلى كلام', en: 'Arabic Text-to-Speech Studio' },
    'brand.api':          { ar: 'استوديو الـ API',            en: 'API Studio' },
    'nav.api':            { ar: '‹/› واجهة الـ API',          en: '‹/› API reference' },
    'nav.studio':         { ar: '🎙 عودة إلى الاستوديو',      en: '🎙 Back to the studio' },
    'lang.toggle':        { ar: 'EN',                          en: 'ع' },
    'lang.toggleTitle':   { ar: 'Switch interface to English', en: 'التبديل إلى العربية' },

    // ── Panels ────────────────────────────────────────────────
    'section.model':      { ar: 'النموذج',        en: 'Model' },
    'section.voice':      { ar: 'الصوت',          en: 'Voice' },
    'section.text':       { ar: 'النص',           en: 'Text' },
    'section.output':     { ar: 'المخرجات',       en: 'Output' },
    'section.compare':    { ar: 'المقارنة',       en: 'Comparison' },
    'section.history':    { ar: 'السجل',          en: 'History' },
    'section.transcribe': { ar: '📝 التفريغ الصوتي', en: '📝 Transcription' },

    // ── Transcription ─────────────────────────────────────────
    'tr.desc': {
      ar: 'ارفع مقطعاً صوتياً أو سجّل من الميكروفون ليحوّله النموذج إلى نص، ثم انقله إلى صندوق النص بالأسفل. المقاطع الطويلة تُقسَّم وتُدمج تلقائياً.',
      en: 'Upload an audio clip or record from your microphone; the model turns it into text you can drop into the box below. Long clips are split and stitched back together automatically.',
    },
    'tr.modelLabel':      { ar: 'النموذج', en: 'Model' },
    'tr.modelNote': {
      ar: 'نسخة NAMAA-Space المكمَّمة (INT8) من نموذج Cohere للتفريغ العربي — عربي/إنجليزي، 16kHz',
      en: "NAMAA-Space's INT8 quantization of Cohere's Arabic ASR model — Arabic/English, 16 kHz",
    },
    'tr.drop':            { ar: 'اسحب ملفاً صوتياً هنا أو اضغط للاختيار', en: 'Drop an audio file here, or click to choose' },
    'tr.langTitle':       { ar: 'لغة التفريغ — النموذج يدعم العربية والإنجليزية فقط', en: 'Transcription language — the model supports Arabic and English only' },
    'tr.langAr':          { ar: 'عربي',     en: 'Arabic' },
    'tr.langEn':          { ar: 'إنجليزي',  en: 'English' },
    'tr.punct':           { ar: 'علامات الترقيم', en: 'Punctuation' },
    'tr.punctTitle':      { ar: 'أطفئه للحصول على نص بلا علامات ترقيم وبأحرف صغيرة', en: 'Turn off for text with no punctuation, in lower case' },
    'tr.record':          { ar: '🎙 سجّل',   en: '🎙 Record' },
    'tr.recordTitle':     { ar: 'سجّل مقطعاً من الميكروفون بدل رفع ملف', en: 'Record from the microphone instead of uploading a file' },
    'tr.stop':            { ar: '⏹ إيقاف',  en: '⏹ Stop' },
    'tr.run':             { ar: '▷ فرّغ الصوت', en: '▷ Transcribe' },
    'tr.running':         { ar: '… جاري التفريغ', en: '… transcribing' },
    'tr.busy':            { ar: 'يفرّغ النموذج الصوت…', en: 'The model is transcribing…' },
    'tr.resultTag':       { ar: 'النص المُفرَّغ', en: 'Transcript' },
    'tr.use':             { ar: '✓ استخدمه كنص للتوليد', en: '✓ Use as synthesis text' },
    'tr.empty':           { ar: '(لم يتعرّف النموذج على أي كلام)', en: '(the model did not detect any speech)' },
    'tr.needFile':        { ar: 'اختر ملفاً صوتياً أو سجّل مقطعاً أولاً', en: 'Choose an audio file or record a clip first' },
    'tr.failed':          { ar: 'تعذّر تفريغ الصوت', en: 'Could not transcribe the audio' },
    'tr.moved':           { ar: 'تم نقل النص المُفرَّغ ✓', en: 'Transcript moved ✓' },
    'tr.recordFailed':    { ar: 'تعذّر بدء التسجيل', en: 'Could not start recording' },
    'tr.recording':       { ar: '● جاري التسجيل', en: '● recording' },
    'tr.clip':            { ar: 'تسجيل', en: 'recording' },

    // ── Text box ──────────────────────────────────────────────
    'text.placeholder':   { ar: 'اكتب النص العربي هنا…  |  Type text here…', en: 'Type your text here…  |  اكتب النص هنا…' },
    'text.clear':         { ar: 'مسح', en: 'Clear' },

    // ── Synthesis ─────────────────────────────────────────────
    'synth.run':          { ar: 'توليد الصوت',   en: 'Generate speech' },
    'synth.compare':      { ar: 'قارن النماذج',  en: 'Compare models' },
    'synth.running':      { ar: 'جاري التوليد…', en: 'Generating…' },
    'synth.checking':     { ar: 'جاري التحقق…',  en: 'Checking…' },
    'synth.unavailable':  { ar: 'النموذج غير متاح', en: 'Model unavailable' },
    'synth.loadingModel': { ar: 'جاري تحميل النموذج (قد يستغرق 1–2 دقيقة)…', en: 'Loading the model (may take 1–2 minutes)…' },
    'synth.done':         { ar: 'تم توليد الصوت بنجاح ✓', en: 'Speech generated ✓' },
    'synth.needText':     { ar: 'أدخل نصاً أولاً', en: 'Enter some text first' },

    // ── Player ────────────────────────────────────────────────
    'player.empty':       { ar: 'سيظهر الصوت المولّد هنا بعد الضغط على "توليد الصوت"', en: 'Generated audio will appear here once you press “Generate speech”' },
    'player.download':    { ar: '⬇ تنزيل', en: '⬇ Download' },
    'metric.elapsed':     { ar: 'زمن التوليد', en: 'Generation time' },
    'metric.duration':    { ar: 'مدة الصوت',   en: 'Audio length' },
    'metric.rate':        { ar: 'العينة',      en: 'Sample rate' },
    'badge.generated':    { ar: 'توليد', en: 'generated' },
    'badge.audio':        { ar: 'صوت',   en: 'audio' },

    // ── RTF wording ───────────────────────────────────────────
    'rtf.unknown':        { ar: 'غير معروف',              en: 'unknown' },
    'rtf.fast':           { ar: 'أسرع من الزمن الحقيقي',  en: 'faster than real time' },
    'rtf.ok':             { ar: 'مقبول للتجارب',          en: 'fine for testing' },
    'rtf.slow':           { ar: 'بطيء على CPU',           en: 'slow on CPU' },
    'rtf.verySlow':       { ar: 'بطيء جداً على CPU',      en: 'very slow on CPU' },

    // ── Worker status ─────────────────────────────────────────
    'st.online':          { ar: '● متاح',              en: '● available' },
    'st.offline':         { ar: '● غير متاح',          en: '● offline' },
    'st.checking':        { ar: '● جاري التحقق…',      en: '● checking…' },
    'st.loading':         { ar: '● جاري التحميل…',     en: '● loading…' },
    'st.notLoaded':       { ar: '● متاح - غير محمّل',  en: '● available – not loaded' },
    'st.loadBtn':         { ar: 'تحميل النموذج',       en: 'Load model' },
    'st.loadingBtn':      { ar: 'جاري التحميل…',       en: 'Loading…' },
    'st.loadingToast':    { ar: 'جاري تحميل {name}… (قد يستغرق 2–3 دقائق)', en: 'Loading {name}… (may take 2–3 minutes)' },
    'st.loadedToast':     { ar: '✓ تم تحميل {name}',   en: '✓ {name} loaded' },
    'st.loadFailed':      { ar: 'تعذّر تحميل النموذج: {err}', en: 'Could not load the model: {err}' },

    // ── Voices ────────────────────────────────────────────────
    'voice.none':         { ar: 'بدون استنساخ', en: 'No cloning' },
    'voice.abeer':        { ar: 'عبير — سعودية', en: 'Abeer — Saudi' },
    'voice.ahmed':        { ar: 'أحمد — فصحى',   en: 'Ahmed — MSA' },

    // ── Compare ───────────────────────────────────────────────
    'cmp.toggle':         { ar: 'قارن نفس النص باستخدام كل النماذج المتاحة', en: 'Compare the same text across every available model' },
    'cmp.run':            { ar: 'قارن الآن', en: 'Compare now' },
    'cmp.runN':           { ar: 'قارن الآن ({n})', en: 'Compare now ({n})' },
    'cmp.none':           { ar: 'لا توجد نماذج متاحة', en: 'No models available' },
    'cmp.expandAll':      { ar: 'فتح الكل', en: 'Expand all' },
    'cmp.collapseAll':    { ar: 'طيّ الكل', en: 'Collapse all' },
    'cmp.clearAll':       { ar: 'مسح الكل', en: 'Clear all' },
    'cmp.confirmClear':   { ar: 'مسح كل المقارنات المحفوظة؟', en: 'Clear every saved comparison?' },
    'cmp.needModel':      { ar: 'اختر نموذجاً واحداً على الأقل', en: 'Select at least one model' },
    'cmp.waiting':        { ar: 'في الانتظار…', en: 'Waiting…' },
    'cmp.generating':     { ar: 'جاري التوليد…', en: 'Generating…' },
    'cmp.retrying':       { ar: 'جاري إعادة المحاولة…', en: 'Retrying…' },
    'cmp.retry':          { ar: '↻ إعادة المحاولة', en: '↻ Retry' },
    'cmp.retried':        { ar: 'تمت إعادة التوليد ✓', en: 'Regenerated ✓' },
    'cmp.retryFailed':    { ar: 'فشلت إعادة المحاولة: {err}', en: 'Retry failed: {err}' },
    'cmp.busy':           { ar: 'انتظر حتى تكتمل المقارنة الحالية', en: 'Wait for the current comparison to finish' },
    'cmp.notFound':       { ar: 'تعذّر العثور على المقارنة', en: 'Comparison not found' },
    'cmp.incomplete':     { ar: 'لم تكتمل المقارنة', en: 'Comparison did not finish' },
    'cmp.preparing':      { ar: 'جاري تحضير مقارنة {n} نماذج…', en: 'Preparing a comparison of {n} models…' },
    'cmp.progress':       { ar: 'جاري المقارنة {i}/{n}', en: 'Comparing {i}/{n}' },
    'cmp.progressHint':   { ar: '{p} — قد يحتاج النموذج غير المحمّل عدة دقائق', en: '{p} — an unloaded model can take several minutes' },
    'cmp.doneErr':        { ar: 'اكتملت المقارنة مع أخطاء', en: 'Comparison finished with errors' },
    'cmp.done':           { ar: 'اكتملت المقارنة', en: 'Comparison finished' },
    'cmp.startFailed':    { ar: 'تعذّر بدء المقارنة: {err}', en: 'Could not start the comparison: {err}' },
    'cmp.summary':        { ar: 'ملخص المقارنة', en: 'Comparison summary' },
    'cmp.fastest':        { ar: 'أسرع توليد', en: 'Fastest' },
    'cmp.bestRtf':        { ar: 'أفضل RTF', en: 'Best RTF' },
    'cmp.highestRate':    { ar: 'أعلى عينة', en: 'Highest sample rate' },
    'cmp.count':          { ar: 'عدد النتائج', en: 'Results' },
    'cmp.hasErrors':      { ar: 'توجد أخطاء', en: 'some failed' },
    'cmp.allDone':        { ar: 'كلها اكتملت', en: 'all completed' },
    'cmp.models':         { ar: 'نماذج', en: 'models' },
    'cmp.errors':         { ar: 'خطأ', en: 'error(s)' },

    // ── History ───────────────────────────────────────────────
    'hist.collapse':      { ar: 'طي',  en: 'Collapse' },
    'hist.expand':        { ar: 'فتح', en: 'Expand' },
    'hist.collapseTitle': { ar: 'طي السجل',  en: 'Collapse history' },
    'hist.expandTitle':   { ar: 'فتح السجل', en: 'Expand history' },
    'hist.all':           { ar: 'كل النماذج', en: 'All models' },
    'hist.clear':         { ar: 'مسح الكل', en: 'Clear all' },
    'hist.confirmClear':  { ar: 'هل تريد مسح جميع سجلات التوليد؟', en: 'Clear the entire generation history?' },
    'hist.empty':         { ar: 'لا توجد مقاطع صوتية بعد', en: 'No audio yet' },
    'hist.play':          { ar: 'تشغيل', en: 'Play' },
    'hist.download':      { ar: 'تنزيل', en: 'Download' },
    'hist.delete':        { ar: 'حذف', en: 'Delete' },

    // Relative timestamps — short units, kept terse for the compact history rows.
    'ago.s':              { ar: 'ث', en: 's' },
    'ago.m':              { ar: 'د', en: 'm' },
    'ago.h':              { ar: 'س', en: 'h' },
    'ago.d':              { ar: 'ي', en: 'd' },

    // ── Models ────────────────────────────────────────────────
    'model.ft.name':      { ar: 'OmniVoice المحسّن', en: 'OmniVoice fine-tuned' },
    'model.ft.role': {
      ar: 'أفضل نسخة — بعد الضبط الدقيق على بيانات سعودية عالية الجودة (saudi_hq_ft/checkpoint-2500). الخيار الافتراضي.',
      en: 'The best variant — fine-tuned on high-quality Saudi data (saudi_hq_ft/checkpoint-2500). The default choice.',
    },
    'model.ft.compareNote': { ar: 'النسخة المحسّنة — قارِنها بالأصلية.', en: 'The fine-tuned variant — compare it against the base.' },
    'model.base.name':    { ar: 'OmniVoice الأصلي', en: 'OmniVoice base' },
    'model.base.role': {
      ar: 'النموذج الأصلي k2-fsa/OmniVoice بدون ضبط — خط أساس للمقارنة، وأوسع تغطية لغات (600+).',
      en: 'The stock k2-fsa/OmniVoice checkpoint, unmodified — a comparison baseline with the widest language coverage (600+).',
    },
    'model.base.compareNote': { ar: 'الأصل بدون ضبط — خط الأساس.', en: 'Unmodified base — the baseline.' },
    'model.trait.arabic': { ar: 'الأفضل للعربية', en: 'Best for Arabic' },
    'model.trait.langs':  { ar: '600+ لغة', en: '600+ languages' },

    'model.profile.bestUse': { ar: 'أفضل استخدام', en: 'Best for' },
    'model.profile.control': { ar: 'التحكم',       en: 'Control' },
    'model.profile.note':    { ar: 'ملاحظة',       en: 'Note' },
    'model.ft.bestUse': {
      ar: 'الإنتاج: نطق عربي/سعودي أفضل من الأصل، مع استنساخ الأصوات المضمّنة (عبير/أحمد).',
      en: 'Production: better Arabic/Saudi pronunciation than the base, with cloning of the bundled voices (Abeer/Ahmed).',
    },
    'model.base.bestUse': {
      ar: 'خط أساس للمقارنة مع النسخة المحسّنة، أو نقل صوت مرجعي بين اللغات.',
      en: 'A baseline to compare the fine-tune against, or to carry a reference voice across languages.',
    },
    'model.control': {
      ar: 'اللهجة عبر لغة النموذج تلقائياً؛ الجنس/العمر/الأسلوب عبر instruct الإنجليزي + صوت مرجعي اختياري.',
      en: 'Dialect rides the model language automatically; gender/age/style via the English instruct field plus an optional reference clip.',
    },
    'model.ft.note': {
      ar: 'يتطلب أوزان الـ checkpoint على السيرفر (models/omnivoice/best_finetuned).',
      en: 'Requires the checkpoint weights on the server (models/omnivoice/best_finetuned).',
    },
    'model.base.note': {
      ar: 'يشارك نفس العامل (worker)؛ التبديل بين النسختين يعيد تحميل النموذج (دقائق على CPU).',
      en: 'Shares the same worker; switching variants reloads the model (minutes on CPU).',
    },

    // ── Dialect / persona pickers ─────────────────────────────
    'dialect.msa':        { ar: 'الفصحى', en: 'MSA' },
    'dialect.saudi':      { ar: 'سعودي',  en: 'Saudi' },
    'dialect.egyptian':   { ar: 'مصري',   en: 'Egyptian' },
    'attr.dialect':       { ar: 'اللهجة', en: 'Dialect' },
    'attr.gender':        { ar: 'الجنس',  en: 'Gender' },
    'attr.age':           { ar: 'العمر',  en: 'Age' },
    'opt.auto':           { ar: 'تلقائي', en: 'Auto' },
    'gender.male':        { ar: 'ذكر',    en: 'Male' },
    'gender.female':      { ar: 'أنثى',   en: 'Female' },
    'age.young':          { ar: 'شاب',    en: 'Young' },
    'age.middle':         { ar: 'متوسط',  en: 'Middle-aged' },
    'age.old':            { ar: 'كبير السن', en: 'Older' },
    'lang.locked':        { ar: 'اللغة مثبّتة على العربية', en: 'Language is locked to Arabic' },
    'lang.lockedChip':    { ar: '🔒 العربية', en: '🔒 Arabic' },
    'lang.lockedHint': {
      ar: 'العربية مفروضة على كل النماذج؛ اختر اللهجة والجنس والعمر وتُحقن تلقائياً في كل طلب.',
      en: 'Arabic is enforced for every model; pick dialect, gender and age and they are injected into each request.',
    },

    'persona.support':    { ar: 'خدمة العملاء', en: 'Customer service' },
    'persona.booking':    { ar: 'وكيل حجوزات', en: 'Booking agent' },
    'persona.story':      { ar: 'سرد قصة',     en: 'Storytelling' },
    'persona.announce':   { ar: 'إعلان',       en: 'Announcement' },

    // ── Voice-cloning fields (advanced panels) ────────────────
    'clone.refAudio':     { ar: 'صوت مرجعي', en: 'Reference audio' },
    'clone.refText':      { ar: 'نص مرجعي',  en: 'Reference text' },
    'clone.refWav':       { ar: 'مرجع Basic', en: 'Basic reference' },
    'clone.promptWav':    { ar: 'صوت Prompt', en: 'Prompt audio' },
    'clone.promptText':   { ar: 'نص Prompt',  en: 'Prompt text' },
    'clone.zoneLabel':    { ar: 'الصوت المرجعي (WAV 5–30 ثانية)', en: 'Reference audio (WAV, 5–30 s)' },
    'clone.textLabel':    { ar: 'نص الصوت المرجعي (اختياري)', en: 'Reference transcript (optional)' },
    'clone.textPh':       { ar: 'النص المنطوق في الصوت المرجعي…', en: 'What is spoken in the reference clip…' },
    'clone.drop':         { ar: 'اسحب ملف WAV هنا أو اضغط للاختيار', en: 'Drop a WAV here, or click to choose' },
    'tag.add':            { ar: 'أضف إلى النص', en: 'Add to the text' },

    // ── Manual-override panel ─────────────────────────────────
    'ov.title':           { ar: '📤 الإدخال الفعلي المُرسَل إلى النموذج', en: '📤 What actually gets sent to the model' },
    'ov.sent':            { ar: '📤 ما أُرسل فعلياً إلى النموذج', en: '📤 What was actually sent to the model' },
    'ov.revert':          { ar: '↺ رجوع للتلقائي', en: '↺ Back to automatic' },
    'ov.edit':            { ar: '✏️ تعديل يدوي',   en: '✏️ Edit manually' },
    'ov.langLine':        { ar: 'لغة النموذج (language)', en: 'Model language' },
    'ov.instruct':        { ar: 'وصف الصوت (instruct)', en: 'Voice description (instruct)' },
    'ov.text':            { ar: 'النص (text)', en: 'Text' },
    'ov.textSent':        { ar: 'النص المُرسَل (text)', en: 'Text sent' },
    'ov.arabic':          { ar: 'العربية', en: 'Arabic' },
    'ov.noteDialect':     { ar: 'يُرسَل المحتوى أعلاه حرفياً (بدون حقن الجنس/العمر)؛ لهجة اللغة العربية تبقى مُطبَّقة عبر لغة النموذج.',
                            en: 'The content above is sent verbatim (no gender/age injection); the Arabic dialect still applies via the model language.' },
    'ov.notePlain':       { ar: 'يُرسَل المحتوى أعلاه إلى النموذج حرفياً (بدون حقن اللهجة/الجنس/العمر).',
                            en: 'The content above is sent to the model verbatim (no dialect/gender/age injection).' },
    'ov.hint':            { ar: 'وضع التعديل اليدوي: {note} اترك الحقل فارغاً للرجوع إلى القيمة التلقائية.',
                            en: 'Manual mode: {note} Leave a field empty to fall back to the automatic value.' },

    // ── Compose / prepare agents ──────────────────────────────
    'ag.composing':       { ar: '… جاري التأليف', en: '… composing' },
    'ag.composeBusy':     { ar: 'يكتب الوكيل النص ويضبط إعدادات النموذجين…', en: 'The agent is writing the text and tuning both models…' },
    'ag.composeDone':     { ar: '✓ تم ضبط النموذجين', en: '✓ Both models configured' },
    'ag.composeToast':    { ar: 'تم تأليف النص وضبط النموذجين ✓', en: 'Text composed and models configured ✓' },
    'ag.composeFailed':   { ar: 'تعذّر التأليف التلقائي', en: 'Auto-compose failed' },
    'ag.compose':         { ar: '✨ أكمل بالذكاء الاصطناعي', en: '✨ Complete with AI' },
    'ag.noText':          { ar: 'لا يوجد نص لتحضيره', en: 'No text to prepare' },
    'ag.pickOption':      { ar: 'فعِّل «الأرقام→كلمات» أو «تشكيل» أولاً', en: 'Enable “numbers → words” or “diacritics” first' },
    'ag.preparing':       { ar: '… جاري التحضير', en: '… preparing' },
    'ag.prepBusy':        { ar: 'يحضّر الوكيل النص…', en: 'The agent is preparing the text…' },
    'ag.prepDone':        { ar: '✓ جاهز — راجِع المقارنة ثم اعتمد', en: '✓ Ready — review the diff, then apply' },
    'ag.prepFailed':      { ar: 'تعذّر تحضير النص', en: 'Could not prepare the text' },
    'ag.prep':            { ar: '✦ حضّر النص', en: '✦ Prepare text' },
    'ag.applied':         { ar: 'تم اعتماد النص ✓ — راجِعه ثم ولّد', en: 'Text applied ✓ — review it, then generate' },

    // ── API playground ────────────────────────────────────────
    'api.tagline':        { ar: 'واجهة برمجية مفتوحة: تفريغ صوتي وتوليد كلام', en: 'Open HTTP API: transcription and speech synthesis' },
    'api.intro1':         { ar: 'كل نقطة نهاية أدناه قابلة للتجربة مباشرة من هذه الصفحة، ومعها أمر curl جاهز للنسخ.',
                            en: 'Every endpoint below can be tried straight from this page, each with a ready-to-copy curl command.' },
    'api.intro2':         { ar: 'الخادم هو نفسه الذي يخدم هذه الصفحة، لذا تعمل المسارات النسبية كما هي من أي عميل على الشبكة.',
                            en: 'The API is served by the same host as this page, so the relative paths work as-is from any client on the network.' },
    'api.base':           { ar: 'عنوان الخدمة', en: 'Service address' },
    'api.model':          { ar: 'النموذج', en: 'Model' },
    'api.returns':        { ar: 'يعيد', en: 'Returns' },
    'api.try':            { ar: '▷ جرّب الآن', en: '▷ Try it' },
    'api.running':        { ar: '… جاري التنفيذ', en: '… running' },
    'api.copy':           { ar: 'نسخ', en: 'Copy' },
    'api.copied':         { ar: 'تم النسخ ✓', en: 'Copied ✓' },
    'api.failed':         { ar: 'فشل الطلب', en: 'Request failed' },
    'api.emptyOpt':       { ar: '(فارغ)', en: '(empty)' },
    'api.missingField':   { ar: 'الحقل المطلوب "{name}" فارغ', en: 'Required field “{name}” is empty' },

    'ep.status.title':    { ar: 'حالة جميع العمّال', en: 'Status of every worker' },
    'ep.status.desc':     { ar: 'حالة كل نموذج: هل العامل يعمل، وهل حُمِّل النموذج في الذاكرة بعد.',
                            en: 'Per-model status: whether the worker is up, and whether its model is resident in memory yet.' },
    'ep.tr.title':        { ar: 'تفريغ صوتي (Cohere Transcribe Arabic INT8)', en: 'Transcription (Cohere Transcribe Arabic INT8)' },
    'ep.tr.desc':         { ar: 'صوت ← نص عربي أو إنجليزي. يقبل wav/mp3/m4a/webm ويعيد أخذ العينات إلى 16kHz تلقائياً. المقاطع الأطول من نافذة النموذج تُقسَّم وتُدمج نتائجها تلقائياً.',
                            en: 'Audio → Arabic or English text. Accepts wav/mp3/m4a/webm and resamples to 16 kHz automatically. Clips longer than the model window are split and their results merged.' },
    'ep.tr.model':        { ar: 'نسخة NAMAA-Space المكمَّمة (INT8) من نموذج Cohere للتفريغ العربي',
                            en: "NAMAA-Space's INT8 quantization of Cohere's Arabic transcription model" },
    'ep.tr.audio':        { ar: 'ملف صوتي — يخضع لحد حجم الطلب في الخادم', en: 'Audio file — subject to the server request-size limit' },
    'ep.tr.lang':         { ar: 'النموذج عربي/إنجليزي فقط', en: 'The model handles Arabic/English only' },
    'ep.tr.punct':        { ar: 'false ⇐ نص بلا ترقيم', en: 'false ⇒ text without punctuation' },
    'ep.synth.title':     { ar: 'توليد كلام', en: 'Speech synthesis' },
    'ep.synth.desc':      { ar: 'نص ← ملف wav. المعاملات الإضافية تختلف بين النموذجين: الاسمان أدناه نسختان من OmniVoice (المحسّنة والأصلية) تتشاركان نفس العامل.',
                            en: 'Text → a wav file. Extra parameters differ per model: the two names below are OmniVoice variants (fine-tuned and base) sharing one worker.' },
    'ep.synth.voice':     { ar: 'اسم صوت مدمج، أو فارغ لصوت النموذج', en: 'A bundled voice name, or empty for the model’s own voice' },
    'ep.synth.gender':    { ar: 'فارغ = اختيار النموذج', en: 'empty = let the model choose' },
    'ep.load.title':      { ar: 'تحميل نموذج مسبقاً', en: 'Preload a model' },
    'ep.load.desc':       { ar: 'يحمّل أوزان النموذج في الذاكرة الآن بدل انتظار أول طلب. مفيد لتفادي بطء أول استدعاء.',
                            en: 'Loads the model weights into memory now instead of on the first request — avoids a slow first call.' },
    'ep.one.title':       { ar: 'حالة نموذج واحد', en: 'Status of one model' },
    'ep.one.desc':        { ar: 'نفس محتوى ‎/api/status‎ لكن لنموذج بعينه.', en: 'The same payload as /api/status, for a single model.' },
    'ep.hist.title':      { ar: 'سجل المخرجات', en: 'Output history' },
    'ep.hist.desc':       { ar: 'آخر الملفات المحفوظة على الخادم مع مدخلاتها. لـ transcribe يحتوي الحقل text على النص المُفرَّغ.',
                            en: 'The most recent files saved on the server with their inputs. For transcribe, the text field holds the transcript.' },
    'ep.prep.title':      { ar: 'تحضير النص (وكيل)', en: 'Text preparation (agent)' },
    'ep.prep.desc':       { ar: 'يحوّل الأرقام والتواريخ والاختصارات إلى كلمات منطوقة، ويضيف التشكيل اختيارياً. يعمل على النص فقط.',
                            en: 'Turns numbers, dates and abbreviations into spoken words, and optionally adds diacritics. Text only.' },
    'ep.compose.title':   { ar: 'التأليف التلقائي (وكيل)', en: 'Auto-compose (agent)' },
    'ep.compose.desc':    { ar: 'يكتب نصاً عربياً للمهمة المطلوبة ويضبط إعدادات النموذجين. يتطلب OPENAI_API_KEY على الخادم.',
                            en: 'Writes Arabic text for the requested task and tunes both models. Requires OPENAI_API_KEY on the server.' },
    'ep.audio.title':     { ar: 'تنزيل ملف صوتي', en: 'Download an audio file' },
    'ep.audio.desc':      { ar: 'يخدم أي ملف يظهر في السجل أو في ردّ التوليد/التفريغ. رابط مباشر — لا حاجة لتجربته من هنا.',
                            en: 'Serves any file named in the history or in a synthesis/transcription response. A direct link — no need to try it here.' },

    // ── Misc ──────────────────────────────────────────────────
    'misc.default':       { ar: 'افتراضي', en: 'default' },
    'misc.noParams':      { ar: 'لا توجد معاملات إضافية.', en: 'No additional parameters.' },
    'misc.error':         { ar: 'خطأ', en: 'Error' },
    'misc.bootWarn':      { ar: 'تم تشغيل الأزرار، لكن تعذّر استعادة بعض بيانات المتصفح القديمة', en: 'Controls are live, but some older browser data could not be restored' },
  };

  const SUPPORTED = ['ar', 'en'];
  const DIR = { ar: 'rtl', en: 'ltr' };

  let current = (() => {
    try {
      const saved = localStorage.getItem(STORE_KEY);
      if (SUPPORTED.includes(saved)) return saved;
    } catch { /* private mode: fall through to the default */ }
    return 'ar';
  })();

  // Missing keys render as the key itself rather than blank — a visible failure is
  // easier to spot and fix than a silently empty label.
  function t(key, vars) {
    const entry = STRINGS[key];
    // Deliberately not `??`: the frontend-contract tests parse this file with the host's
    // node, which predates nullish coalescing, and they load i18n.js before every script.
    let s = entry ? (entry[current] !== undefined ? entry[current] : entry.ar) : key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v));
    }
    return s;
  }

  // Rewrites everything tagged in the markup. Attribute variants exist because a
  // tooltip or placeholder cannot be expressed as a text node.
  function apply(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach(el => {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    scope.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = t(el.getAttribute('data-i18n-title'));
    });
    scope.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    });
    document.documentElement.lang = current;
    document.documentElement.dir = DIR[current];
  }

  function set(next) {
    if (!SUPPORTED.includes(next) || next === current) return;
    current = next;
    try { localStorage.setItem(STORE_KEY, next); } catch { /* not fatal */ }
    apply();
    // Panels built imperatively (model cards, history rows) re-render off this.
    document.dispatchEvent(new CustomEvent('languagechange', { detail: { lang: next } }));
  }

  const get = () => current;
  const other = () => (current === 'ar' ? 'en' : 'ar');

  return { t, apply, set, get, other, SUPPORTED };
})();

const t = (key, vars) => I18N.t(key, vars);
