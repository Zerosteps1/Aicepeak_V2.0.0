// Aicepeak · Document upload (add documents → check → extract)
//
// How it works
//   1. The browser asks the backend for one upload URL (Azure Blob SAS) per file, PUTs the file straight
//      into Blob Storage, then tells the backend the upload is complete.
//   2. The backend checks each document (is it a financial report?), renders a preview of its FIRST PAGE,
//      and later extracts positions page by page.
//   3. Everything the backend does reaches the page as Server-Sent Events (see EVENTS). The page never
//      guesses progress: every animation starts or stops on an event, an upload callback or a click.
//
// The page talks to `api`. CONFIG.useMock = true swaps in mockApi, which plays the same events with timers,
// so the prototype runs without a backend. Set it to false (or open with ?mock=0) for the real API.

(() => {
  'use strict';

  const params = new URLSearchParams(location.search);

  // ---------- Settings ----------
  const CONFIG = {
    useMock: params.get('mock') !== '0',
    apiBase: '/api',
    projectId: params.get('project'),               // the project this page fills; the page is opened for an existing project
    projectName: params.get('name') || 'Alpine Paper',
    positionsUrl: '/projekte/{projectId}/positionen', // target of the continue-to-positions button
    cancelUrl: null,                                 // after cancel: null = back to the empty drop tray, or a URL to leave to
    accept: ['pdf', 'doc', 'docx', 'xls', 'xlsx'],
    maxFileBytes: 50 * 1024 * 1024,
    stripAbovePages: 150,                            // above this, a line is one continuous strip instead of one segment per page
    foundRows: 3,                                    // rows in the latest-positions table
    statementLabels: {                               // backend keys → badge words on a checked sheet
      income_statement: 'GuV',
      balance_sheet: 'Bilanz',
      cash_flow: 'Kapitalfluss',
      plan: 'Planung'
    },
    mockTiming: { sampleGapMs: 400, uploadMs: 900, checkMs: 2400, pageMs: 400 }
  };

  // Server-Sent Events from GET {apiBase}/projects/{projectId}/events (payloads in the handoff)
  const EVENTS = [
    'document.checking',    // { documentId, page, pages, unit }            checking started / reached a page
    'document.preview',     // { documentId, previewUrl }                    first page rendered
    'document.checked',     // { documentId, result, statements[] }          result: usable | not_financial
    'document.failed',      // { documentId, code, message }
    'extraction.started',   // { documentId, pages }                         reading of this document begins
    'extraction.page',      // { documentId, pagesRead, positions }          positions = project total so far
    'extraction.position',  // { documentId, page, name, value, period, source }
    'extraction.finished',  // { positions }
    'extraction.failed'     // { code, message }
  ];

  // ---------- Real API ----------
  const httpApi = {
    async getState(pid) {
      return json(await fetch(`${CONFIG.apiBase}/projects/${pid}`, { credentials: 'include' }));
    },
    // One SAS upload URL per file: { documents: [{ documentId, uploadUrl, blobName }] }, same order as files
    async registerDocuments(pid, files) {
      return json(await fetch(`${CONFIG.apiBase}/projects/${pid}/documents`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: files.map((f) => ({ name: f.name, size: f.size, contentType: f.type || 'application/octet-stream' })) })
      }));
    },
    // Straight into Azure Blob Storage. XHR instead of fetch for upload progress.
    uploadToBlob(uploadUrl, file, onProgress) {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('PUT', uploadUrl);
        xhr.setRequestHeader('x-ms-blob-type', 'BlockBlob');
        xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
        xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
        xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error('upload ' + xhr.status)));
        xhr.onerror = () => reject(new Error('upload network error'));
        xhr.send(file);
      });
    },
    async completeUpload(pid, documentId) {
      return json(await fetch(`${CONFIG.apiBase}/projects/${pid}/documents/${documentId}/complete`, { method: 'POST', credentials: 'include' }));
    },
    async removeDocument(pid, documentId) {
      return json(await fetch(`${CONFIG.apiBase}/projects/${pid}/documents/${documentId}`, { method: 'DELETE', credentials: 'include' }));
    },
    async startExtraction(pid) {
      return json(await fetch(`${CONFIG.apiBase}/projects/${pid}/extraction`, { method: 'POST', credentials: 'include' }));
    },
    async cancel(pid) {
      return json(await fetch(`${CONFIG.apiBase}/projects/${pid}/cancel`, { method: 'POST', credentials: 'include' }));
    },
    // Same origin as the backend, so the session cookie authenticates the stream.
    subscribe(pid, onEvent, onReconnect) {
      const es = new EventSource(`${CONFIG.apiBase}/projects/${pid}/events`, { withCredentials: true });
      let opened = false;
      es.addEventListener('open', () => { if (opened) onReconnect(); opened = true; });
      EVENTS.forEach((type) => es.addEventListener(type, (e) => onEvent(type, JSON.parse(e.data))));
      return () => es.close();
    }
  };

  async function json(res) {
    if (!res.ok) throw new Error(res.status + ' ' + res.url);
    return res.status === 204 ? null : res.json();
  }

  // ---------- Mock API: same interface, same events, played with timers ----------
  function createMockApi() {
    const T = CONFIG.mockTiming;
    const listeners = new Set();
    const timers = new Set();
    const docs = new Map();
    const queue = [];
    let seq = 0;
    let checking = false;

    const later = (ms, fn) => { const t = setTimeout(() => { timers.delete(t); fn(); }, ms); timers.add(t); };
    const emit = (type, data) => later(0, () => listeners.forEach((fn) => fn(type, data)));

    // The four sample documents of the design, then a rough guess for any other file
    const SAMPLES = {
      'Jahresabschluss_2025_Alpine_Paper.pdf': { pages: 38, result: 'usable', statements: ['income_statement', 'balance_sheet'], perPage: 3.8 },
      'Planung_2027_v3.xlsx': { pages: 6, result: 'usable', statements: ['plan'], perPage: 12 },
      'Kapitalflussrechnung_Q3_2026.pdf': { pages: 9, result: 'usable', statements: ['cash_flow'], perPage: 3 },
      'Protokoll_Aufsichtsrat_Oktober.docx': { pages: 12, result: 'not_financial', statements: [] }
    };
    const guess = (f) => {
      const ext = extension(f.name);
      const n = f.name.toLowerCase();
      return SAMPLES[f.name] || {
        pages: Math.max(1, Math.round(f.size / (110 * 1024))),
        result: ext === 'doc' || ext === 'docx' ? 'not_financial' : 'usable',
        statements: /plan/.test(n) ? ['plan'] : /kapitalfluss|cash/.test(n) ? ['cash_flow'] : ['income_statement', 'balance_sheet'],
        perPage: 3
      };
    };

    // Positions the mock "finds", by the kind of statement it reads
    const POOL = {
      income_statement: [['Umsatzerlöse', '184 300', '2025 · Ist'], ['Materialaufwand', '−18 650', '2025 · Ist'], ['Personalaufwand', '−12 400', '2025 · Ist'], ['Abschreibungen', '−8 210', '2025 · Ist'], ['Sonstige betriebliche Aufwendungen', '−6 900', '2025 · Ist']],
      balance_sheet: [['Sachanlagen', '96 820', '31.12.2025'], ['Vorräte', '21 470', '31.12.2025'], ['Verbindlichkeiten aus Lieferungen', '17 930', '31.12.2025']],
      plan: [['Umsatzerlöse', '196 000', '2027 · Plan'], ['Investitionen', '−14 500', '2027 · Plan']],
      cash_flow: [['Cashflow aus laufender Tätigkeit', '9 870', 'Q3 2026'], ['Cashflow aus Finanzierung', '−3 120', 'Q3 2026']]
    };

    function runChecks() {
      if (checking || !queue.length) return;
      checking = true;
      const id = queue.shift();
      const d = docs.get(id);
      if (!d) { checking = false; runChecks(); return; }
      const unit = d.unit;
      const steps = Math.min(8, d.pages);
      emit('document.checking', { documentId: id, page: 1, pages: d.pages, unit });
      later(300, () => emit('document.preview', { documentId: id, previewUrl: 'assets/sample-first-page.jpg' }));
      for (let k = 2; k <= steps; k++) {
        later((T.checkMs / steps) * (k - 1), () => emit('document.checking', { documentId: id, page: Math.ceil((k / steps) * d.pages), pages: d.pages, unit }));
      }
      later(T.checkMs, () => {
        if (docs.has(id)) emit('document.checked', { documentId: id, result: d.result, statements: d.statements });
        checking = false;
        runChecks();
      });
    }

    function runExtraction() {
      const usable = [...docs.entries()].filter(([, d]) => d.result === 'usable' && !d.removed);
      let positions = 0;
      let global = 0;
      let at = 0;
      usable.forEach(([id, d]) => {
        later(at, () => emit('extraction.started', { documentId: id, pages: d.pages }));
        for (let p = 1; p <= d.pages; p++) {
          at += T.pageMs;
          const page = p;
          later(at, () => {
            global++;
            positions = Math.round(positions + d.perPage);
            emit('extraction.page', { documentId: id, pagesRead: page, positions });
            if (global % 3 === 0) {
              const pool = d.statements.flatMap((k) => POOL[k] || []);
              const [name, value, period] = pool[(global / 3 - 1) % pool.length];
              const short = d.name.replace(/\.[^.]+$/, '').split('_').slice(0, 2).join('_');
              emit('extraction.position', { documentId: id, page, name, value, period, source: `${short} · ${d.unit === 'Bl.' ? 'Blatt' : 'S.'} ${page}` });
            }
          });
        }
      });
      later(at + T.pageMs, () => emit('extraction.finished', { positions }));
    }

    return {
      async getState() {
        return { project: { id: 'mock', name: CONFIG.projectName }, documents: [], extraction: { status: 'idle', positions: 0 } };
      },
      async registerDocuments(pid, files) {
        return {
          documents: files.map((f) => {
            const id = 'doc_' + (++seq);
            const ext = extension(f.name);
            docs.set(id, Object.assign({ name: f.name, unit: ext === 'xls' || ext === 'xlsx' ? 'Bl.' : 'S.' }, guess(f)));
            return { documentId: id, uploadUrl: 'mock://' + id, blobName: `projects/${pid}/documents/${id}/original.${ext}` };
          })
        };
      },
      uploadToBlob(uploadUrl, file, onProgress) {
        return new Promise((resolve) => {
          [20, 40, 60, 80, 100].forEach((p, i) => later((T.uploadMs / 5) * (i + 1), () => { onProgress(p); if (p === 100) resolve(); }));
        });
      },
      async completeUpload(pid, id) { queue.push(id); runChecks(); return null; },
      async removeDocument(pid, id) {
        const d = docs.get(id);
        if (d) d.removed = true;
        const i = queue.indexOf(id);
        if (i >= 0) queue.splice(i, 1);
        return null;
      },
      async startExtraction() { runExtraction(); return null; },
      async cancel() {
        timers.forEach(clearTimeout); timers.clear();
        docs.clear(); queue.length = 0; checking = false;
        return null;
      },
      subscribe(pid, onEvent) { listeners.add(onEvent); return () => listeners.delete(onEvent); }
    };
  }

  const api = CONFIG.useMock ? createMockApi() : httpApi;

  // ---------- State ----------
  // doc.status: uploading → queued → checking → usable | not_financial   (or failed at any point)
  const state = {
    projectId: CONFIG.projectId || (CONFIG.useMock ? 'mock' : null),
    screen: 'upload',
    docs: new Map(),          // documentId → doc, in the order they were added
    extraction: { status: 'idle', positions: 0 }
  };

  const app = document.getElementById('app');
  const $ = (id) => document.getElementById(id);
  const field = (el, name) => el.querySelector(`[data-field="${name}"]`);
  const fmt = (n) => n.toLocaleString('de-DE');
  const fmtMb = (bytes) => (bytes / 1048576).toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' MB';
  function extension(name) { return (name.split('.').pop() || '').toLowerCase(); }

  // ---------- Theme: ?theme=light|dark, otherwise the system setting ----------
  function applyTheme() {
    const p = params.get('theme');
    const t = p === 'light' || p === 'dark' ? p : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.dataset.theme = t;
  }
  applyTheme();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);

  // ---------- Signal band: its middle at 55 % of the current glass panel ----------
  function placeBand() {
    const panel = state.screen === 'upload' ? $('tray') : $('panel');
    if (!panel || panel.offsetParent === null) return;
    const top = panel.getBoundingClientRect().top - app.getBoundingClientRect().top + panel.offsetHeight * 0.55 - 66;
    app.style.setProperty('--band-top', Math.round(top) + 'px');
  }
  const ro = new ResizeObserver(placeBand);
  ro.observe($('tray'));
  ro.observe($('panel'));
  addEventListener('resize', placeBand);

  // ---------- Step 1 · Documents ----------
  function sheetEl(doc) {
    let el = document.querySelector(`.np-sheet[data-id="${doc.id}"]`);
    if (!el) {
      el = $('tpl-sheet').content.firstElementChild.cloneNode(true);
      el.dataset.id = doc.id;
      field(el, 'remove').addEventListener('click', () => removeDoc(doc.id));
      field(el, 'preview').addEventListener('load', () => { el.dataset.preview = 'true'; });
      $('sheets').append(el);
    }
    return el;
  }

  function renderSheet(doc) {
    const el = sheetEl(doc);
    el.dataset.state = doc.status;
    field(el, 'kind').textContent = extension(doc.name).toUpperCase();
    field(el, 'name').textContent = doc.name;
    field(el, 'name').title = doc.name;
    // Extent: the size until the backend knows the pages
    field(el, 'extent').textContent = doc.pages ? `${doc.pages} ${doc.unit}` : fmtMb(doc.sizeBytes);
    field(el, 'found').textContent = doc.statements.map((s) => CONFIG.statementLabels[s] || s).join(' · ');
    const img = field(el, 'preview');
    if (doc.previewUrl && img.getAttribute('src') !== doc.previewUrl) img.src = doc.previewUrl;
    const word = doc.unit === 'Bl.' ? 'Blatt' : 'Seite';
    const text = {
      uploading: `Wird hochgeladen · ${doc.uploadPct} %`,
      queued: 'Wartet',
      checking: doc.pages ? `Wird gelesen · ${word} ${doc.checkPage}/${doc.pages}` : 'Wird gelesen',
      usable: 'Geprüft',
      not_financial: 'Nicht verwendbar',
      failed: doc.error || 'Fehlgeschlagen'
    }[doc.status];
    field(el, 'state').textContent = text;
    el.setAttribute('aria-label', `${doc.name}: ${text}`);
  }

  function renderUploadSummary() {
    const docs = [...state.docs.values()];
    app.dataset.empty = String(docs.length === 0);
    const bytes = docs.reduce((a, d) => a + d.sizeBytes, 0);
    $('tray-meta').textContent = docs.length
      ? `${docs.length} ${docs.length === 1 ? 'Dokument' : 'Dokumente'} · ${fmtMb(bytes)}`
      : 'Noch keine Dokumente';
    const settled = docs.every((d) => ['usable', 'not_financial', 'failed'].includes(d.status));
    const usable = docs.filter((d) => d.status === 'usable').length;
    const ready = docs.length > 0 && settled && usable > 0;
    $('go-extract').disabled = !ready;
    $('upload-hint').textContent = !docs.length ? 'Weiter, sobald mindestens ein Dokument geprüft ist.'
      : !settled ? 'Dokumente werden geprüft …'
      : !usable ? 'Keines der Dokumente enthält einen Finanzbericht.'
      : usable < docs.length ? `${usable} von ${docs.length} Dokumenten werden verwendet.`
      : 'Alle Dokumente geprüft.';
    placeBand();
  }

  let hintTimer = null;
  function flashHint(text) {
    $('upload-hint').textContent = text;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(renderUploadSummary, 4000);
  }

  async function addFiles(files) {
    const ok = files.filter((f) => CONFIG.accept.includes(extension(f.name)) && f.size <= CONFIG.maxFileBytes);
    const rejected = files.filter((f) => !ok.includes(f));
    if (rejected.length) flashHint(`${rejected.map((f) => f.name).join(', ')}: nur PDF, Word oder Excel bis 50 MB.`);
    if (!ok.length || !state.projectId) return;
    const { documents } = await api.registerDocuments(state.projectId, ok);
    documents.forEach((reg, i) => {
      const file = ok[i];
      const ext = extension(file.name);
      const doc = {
        id: reg.documentId, name: file.name, sizeBytes: file.size, unit: ext === 'xls' || ext === 'xlsx' ? 'Bl.' : 'S.',
        status: 'uploading', uploadPct: 0, pages: null, checkPage: 0, statements: [], previewUrl: null, pagesRead: 0, reading: false, error: null
      };
      state.docs.set(doc.id, doc);
      renderSheet(doc);
      api.uploadToBlob(reg.uploadUrl, file, (pct) => { doc.uploadPct = pct; renderSheet(doc); })
        .then(() => {
          if (!state.docs.has(doc.id)) return;
          if (doc.status === 'uploading') { doc.status = 'queued'; renderSheet(doc); renderUploadSummary(); }
          return api.completeUpload(state.projectId, doc.id);
        })
        .catch(() => { doc.status = 'failed'; doc.error = 'Hochladen fehlgeschlagen'; renderSheet(doc); renderUploadSummary(); });
    });
    renderUploadSummary();
  }

  async function removeDoc(id) {
    state.docs.delete(id);
    document.querySelector(`.np-sheet[data-id="${id}"]`)?.remove();
    renderUploadSummary();
    try { await api.removeDocument(state.projectId, id); } catch (e) { /* the document is gone from the page either way */ }
  }

  // Prototype only: the four sample documents, one after another
  function loadSamples() {
    const samples = [
      { name: 'Jahresabschluss_2025_Alpine_Paper.pdf', size: 4.1 * 1048576, type: 'application/pdf' },
      { name: 'Planung_2027_v3.xlsx', size: 0.6 * 1048576, type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' },
      { name: 'Kapitalflussrechnung_Q3_2026.pdf', size: 1.2 * 1048576, type: 'application/pdf' },
      { name: 'Protokoll_Aufsichtsrat_Oktober.docx', size: 1.4 * 1048576, type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }
    ];
    samples.forEach((f, i) => setTimeout(() => addFiles([f]), i * CONFIG.mockTiming.sampleGapMs));
  }

  // ---------- Step 2 · Extraction ----------
  const usableDocs = () => [...state.docs.values()].filter((d) => d.status === 'usable');

  function buildLines() {
    const host = $('lines');
    host.textContent = '';
    usableDocs().forEach((doc) => {
      const el = $('tpl-line').content.firstElementChild.cloneNode(true);
      el.dataset.id = doc.id;
      field(el, 'kind').textContent = extension(doc.name).toUpperCase();
      field(el, 'name').textContent = doc.name;
      const track = field(el, 'track');
      if (doc.pages > CONFIG.stripAbovePages) {
        track.innerHTML = '<span class="np-strip"><span class="np-strip__fill"></span><span class="np-strip__rest"></span></span>';
      } else {
        for (let i = 0; i < doc.pages; i++) track.append(Object.assign(document.createElement('span'), { className: 'np-seg' }));
      }
      host.append(el);
      renderLine(doc);
    });
  }

  function renderLine(doc) {
    const el = document.querySelector(`.np-line[data-id="${doc.id}"]`);
    if (!el) return;
    const word = doc.unit === 'Bl.' ? 'Blättern' : 'Seiten';
    el.dataset.active = String(doc.pagesRead > 0 || doc.reading);
    el.dataset.reading = String(doc.reading);
    field(el, 'count').textContent = `${doc.pagesRead} / ${doc.pages}`;
    field(el, 'track').setAttribute('aria-label', `${doc.pagesRead} von ${doc.pages} ${word} gelesen`);
    const strip = el.querySelector('.np-strip');
    if (strip) {
      const pct = (doc.pagesRead / doc.pages) * 100 + '%';
      strip.querySelector('.np-strip__fill').style.width = pct;
      strip.querySelector('.np-strip__rest').style.left = pct;
      return;
    }
    el.querySelectorAll('.np-seg').forEach((seg, i) => {
      seg.dataset.s = i < doc.pagesRead ? 'done' : (i === doc.pagesRead && doc.reading ? 'now' : 'todo');
    });
  }

  function renderExtractSummary() {
    const docs = usableDocs();
    const total = docs.reduce((a, d) => a + d.pages, 0);
    const read = docs.reduce((a, d) => a + d.pagesRead, 0);
    const unused = [...state.docs.values()].filter((d) => d.status !== 'usable').map((d) => d.name);
    $('px-meta').textContent = `${docs.length} ${docs.length === 1 ? 'Dokument' : 'Dokumente'} · ${fmt(total)} Seiten`
      + (unused.length ? ` · ${unused.join(', ')} ${unused.length === 1 ? 'wird' : 'werden'} nicht verwendet` : '');
    $('px-read').textContent = fmt(read);
    $('px-total').textContent = fmt(total);
    const bar = $('px-progress');
    bar.setAttribute('aria-valuemax', total);
    bar.setAttribute('aria-valuenow', read);
    bar.setAttribute('aria-valuetext', `${read} von ${total} Seiten`);
    $('px-positions').textContent = fmt(state.extraction.positions);
    const done = state.extraction.status === 'done';
    app.dataset.extraction = state.extraction.status;
    $('go-positions').disabled = !done;
    $('px-hint').textContent = state.extraction.status === 'failed' ? 'Die Extraktion ist abgebrochen. Bitte versuchen Sie es erneut.'
      : done ? 'Alle Seiten gelesen.' : 'Verfügbar, sobald alle Seiten gelesen sind.';
  }

  function addFound(p) {
    const row = $('tpl-found').content.firstElementChild.cloneNode(true);
    ['name', 'value', 'period', 'source'].forEach((k) => { field(row, k).textContent = p[k]; });
    const table = $('found');
    table.prepend(row);
    while (table.children.length > CONFIG.foundRows) table.lastElementChild.remove();
    table.hidden = false;
    $('found-empty').hidden = true;
  }

  // ---------- Screens ----------
  function setScreen(screen) {
    state.screen = screen;
    app.dataset.screen = screen;
    $('screen-upload').hidden = screen !== 'upload';
    $('screen-extract').hidden = screen !== 'extract';
    requestAnimationFrame(placeBand);
  }

  async function startExtraction() {
    $('go-extract').disabled = true;
    try {
      await api.startExtraction(state.projectId);
    } catch (e) {
      flashHint('Die Extraktion konnte nicht gestartet werden.');
      renderUploadSummary();
      return;
    }
    state.extraction = { status: 'running', positions: 0 };
    usableDocs().forEach((d) => { d.pagesRead = 0; d.reading = false; });
    $('found').textContent = '';
    $('found').hidden = true;
    $('found-empty').hidden = false;
    buildLines();
    renderExtractSummary();
    setScreen('extract');
  }

  async function cancel() {
    try { await api.cancel(state.projectId); } catch (e) { /* leave anyway */ }
    if (CONFIG.cancelUrl) { location.href = CONFIG.cancelUrl; return; }
    state.docs.clear();
    state.extraction = { status: 'idle', positions: 0 };
    $('sheets').textContent = '';
    setScreen('upload');
    renderUploadSummary();
  }

  // ---------- Events from the backend ----------
  function onEvent(type, d) {
    const doc = d.documentId ? state.docs.get(d.documentId) : null;
    if (d.documentId && !doc) return; // removed meanwhile
    switch (type) {
      case 'document.checking':
        Object.assign(doc, { status: 'checking', checkPage: d.page, pages: d.pages, unit: d.unit || doc.unit });
        renderSheet(doc); renderUploadSummary();
        break;
      case 'document.preview':
        doc.previewUrl = d.previewUrl;
        renderSheet(doc);
        break;
      case 'document.checked':
        Object.assign(doc, { status: d.result, statements: d.statements || [] });
        renderSheet(doc); renderUploadSummary();
        break;
      case 'document.failed':
        Object.assign(doc, { status: 'failed', error: d.message || 'Fehlgeschlagen' });
        renderSheet(doc); renderUploadSummary();
        break;
      case 'extraction.started':
        Object.assign(doc, { reading: true, pages: d.pages || doc.pages });
        renderLine(doc);
        break;
      case 'extraction.page':
        doc.pagesRead = d.pagesRead;
        if (doc.pagesRead >= doc.pages) doc.reading = false;
        state.extraction.positions = d.positions;
        renderLine(doc); renderExtractSummary();
        break;
      case 'extraction.position':
        addFound(d);
        break;
      case 'extraction.finished':
        state.extraction = { status: 'done', positions: d.positions };
        usableDocs().forEach((x) => { x.reading = false; renderLine(x); });
        renderExtractSummary();
        break;
      case 'extraction.failed':
        state.extraction.status = 'failed';
        usableDocs().forEach((x) => { x.reading = false; renderLine(x); });
        renderExtractSummary();
        break;
    }
  }

  // After a dropped stream reconnects: take the backend's state as the truth
  async function resync() {
    const s = await api.getState(state.projectId);
    if (s.project && s.project.name) document.querySelectorAll('[data-field="project-eyebrow"]').forEach((el) => { el.textContent = `Neues Projekt · ${s.project.name}`; });
    (s.documents || []).forEach((d) => {
      const doc = Object.assign(state.docs.get(d.documentId) || { id: d.documentId, uploadPct: 100, checkPage: 0, reading: false, error: null }, {
        name: d.name, sizeBytes: d.size, unit: d.unit || 'S.', status: d.status, pages: d.pages || null,
        statements: d.statements || [], previewUrl: d.previewUrl || null, pagesRead: d.pagesRead || 0
      });
      state.docs.set(doc.id, doc);
      renderSheet(doc);
    });
    renderUploadSummary();
    const x = s.extraction || {};
    if (x.status === 'running' || x.status === 'done') {
      state.extraction = { status: x.status, positions: x.positions || 0 };
      (x.documents || []).forEach((r) => { const doc = state.docs.get(r.documentId); if (doc) Object.assign(doc, { pagesRead: r.pagesRead, reading: r.reading }); });
      buildLines();
      renderExtractSummary();
      setScreen('extract');
    }
  }

  // ---------- Wiring ----------
  const input = $('file-input');
  input.addEventListener('change', () => { addFiles([...input.files]); input.value = ''; });

  const drop = $('drop');
  addEventListener('dragover', (e) => e.preventDefault());   // a file dropped next to the zone must not open in the tab
  addEventListener('drop', (e) => e.preventDefault());
  drop.addEventListener('dragenter', () => { drop.dataset.over = 'true'; });
  drop.addEventListener('dragleave', (e) => { if (!drop.contains(e.relatedTarget)) drop.dataset.over = 'false'; });
  drop.addEventListener('drop', (e) => { drop.dataset.over = 'false'; addFiles([...e.dataTransfer.files]); });

  app.addEventListener('click', (e) => {
    const t = e.target.closest('[data-action]');
    if (!t) return;
    const a = t.dataset.action;
    if (a === 'cancel') cancel();
    if (a === 'samples') loadSamples();
    if (a === 'extract') startExtraction();
    if (a === 'positions' && state.projectId && !CONFIG.useMock) location.href = CONFIG.positionsUrl.replace('{projectId}', state.projectId);
  });
  app.querySelectorAll('a[href="#"]').forEach((a) => a.addEventListener('click', (e) => e.preventDefault()));

  // ---------- Start ----------
  app.dataset.mock = String(CONFIG.useMock);
  if (!state.projectId) {
    $('upload-hint').textContent = 'Kein Projekt gewählt (?project=…).';
  } else {
    api.subscribe(state.projectId, onEvent, resync);
    resync().catch(() => renderUploadSummary());
  }
  renderUploadSummary();

  // Handy in the browser console: AicepeakNewProject.loadSamples()
  window.AicepeakNewProject = { CONFIG, state, loadSamples, addFiles, cancel };
})();
