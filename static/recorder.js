'use strict';

// ── Microphone capture ────────────────────────────────────────
// Shared by the studio (index.html) and the API playground (api.html): both need to
// hand /api/transcribe a File, and neither should care how MediaRecorder differs
// between browsers.
//
// Two constraints drive the shape of this:
//   • getUserMedia only exists in a secure context — https, or localhost. Served over
//     plain http on a LAN address the browser hides the API entirely, so callers get a
//     readable Arabic reason rather than a TypeError on undefined.
//   • The worker picks its decoder from the *filename suffix* it is handed
//     (transcribe_server.py: `pathlib.Path(audio.filename).suffix or ".wav"`), so the
//     extension must match whatever container MediaRecorder actually produced.
const MicRecorder = (() => {
  // Ordered by preference: opus in webm is the most widely decodable of these, and
  // mp4/aac is the Safari fallback since it refuses webm.
  const CANDIDATES = [
    { mime: 'audio/webm;codecs=opus', ext: '.webm' },
    { mime: 'audio/webm',             ext: '.webm' },
    { mime: 'audio/ogg;codecs=opus',  ext: '.ogg'  },
    { mime: 'audio/mp4',              ext: '.m4a'  },
  ];

  const supported = () =>
    typeof MediaRecorder !== 'undefined' &&
    !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

  function pickFormat() {
    for (const c of CANDIDATES) {
      if (MediaRecorder.isTypeSupported(c.mime)) return c;
    }
    return { mime: '', ext: '.webm' };   // let the browser choose; webm is the usual default
  }

  // Why the failure happened, in the page's language — permission denial and an
  // insecure origin are the two the user can actually act on.
  function reason(err) {
    if (!window.isSecureContext) {
      return 'الميكروفون يحتاج اتصالاً آمناً (https) — افتح الصفحة عبر https أو localhost';
    }
    if (!supported()) return 'المتصفح لا يدعم التسجيل الصوتي';
    const name = err && err.name;
    if (name === 'NotAllowedError')  return 'رُفض إذن الميكروفون — اسمح به من إعدادات المتصفح';
    if (name === 'NotFoundError')    return 'لا يوجد ميكروفون متاح';
    if (name === 'NotReadableError') return 'الميكروفون مستخدم من تطبيق آخر';
    return (err && err.message) || 'تعذّر بدء التسجيل';
  }

  /**
   * Start recording. Resolves to a handle with `stop()` -> Promise<File>.
   * Rejects with a human-readable Arabic Error if the mic is unavailable.
   */
  async function start() {
    if (!supported()) throw new Error(reason(null));

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      throw new Error(reason(e));
    }

    const fmt = pickFormat();
    const rec = new MediaRecorder(stream, fmt.mime ? { mimeType: fmt.mime } : undefined);
    const chunks = [];
    rec.addEventListener('dataavailable', e => { if (e.data && e.data.size) chunks.push(e.data); });
    rec.start();
    const startedAt = Date.now();

    return {
      startedAt,
      stop() {
        return new Promise((resolve, reject) => {
          rec.addEventListener('stop', () => {
            // Always release the mic — the browser keeps its indicator lit otherwise.
            stream.getTracks().forEach(t => t.stop());
            const type = rec.mimeType || fmt.mime || 'audio/webm';
            const blob = new Blob(chunks, { type });
            if (!blob.size) { reject(new Error('لم يُسجَّل أي صوت')); return; }
            // Suffix follows the container the recorder actually used, not the request.
            const ext = (CANDIDATES.find(c => type.startsWith(c.mime.split(';')[0])) || fmt).ext;
            resolve(new File([blob], `recording${ext}`, { type }));
          }, { once: true });
          rec.addEventListener('error', e => reject(new Error(reason(e.error))), { once: true });
          if (rec.state !== 'inactive') rec.stop();
        });
      },
    };
  }

  const fmtElapsed = ms => {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  };

  return { start, supported, fmtElapsed };
})();

// A recorded File has to reach a real <input type="file"> so existing form-reading code
// (which asks for `el.files[0]`) keeps working untouched.
function setInputFile(input, file) {
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
}
