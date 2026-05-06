/* ═══════════════════════════════════════════════════════════
   paraiq-persist.js  —  ParaIQ Session 4: Analysis Persistence
   Auto-saves result containers to localStorage.
   Shows a restore banner on next page visit.
   Self-contained IIFE — no dependencies.
═══════════════════════════════════════════════════════════ */
(function () {

  /* ── Pages to skip (no meaningful results to persist) ── */
  var SKIP_PAGES = ['home', 'dashboard', 'insights', 'index', 'model', 'intake'];

  /* ── Result container selectors to watch ────────────── */
  var TARGETS = [
    '#results',           // analyzer, scorer, risk, citations, compare, timeline, batch
    '#pdfResults',        // redaction
    '#textResults',       // batch text tab
    '#redactionPanel',    // redaction review
    '.results-grid',      // insights / multi-card
    '#contraBody',        // interrogation — contradictions
    '#diarizationBody',   // interrogation — diarization
    '#evasionBody',       // interrogation — evasion
    '#qaBody',            // interrogation — Q&A
  ];

  var MIN_LEN   = 150;   // ignore empty/trivial states
  var SAVE_WAIT = 700;   // debounce ms
  var BANNER_TTL = 12000; // auto-dismiss ms

  var page      = (window.location.pathname.split('/').pop().replace('.html', '') || 'home');
  var STORE_KEY = 'paraiq_persist_' + page;
  var saveTimer = null;

  /* ── Inject banner styles once ───────────────────────── */
  function injectStyles() {
    if (document.getElementById('piq-persist-styles')) return;
    var s = document.createElement('style');
    s.id  = 'piq-persist-styles';
    s.textContent = [
      '#piq-restore-banner {',
      '  position: fixed;',
      '  bottom: 20px;',
      '  left: 50%;',
      '  transform: translateX(-50%);',
      '  z-index: 9999;',
      '  background: #1e293b;',
      '  border: 1px solid #334155;',
      '  border-left: 3px solid #7c3aed;',
      '  color: #e2e8f0;',
      '  font-size: 13px;',
      '  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;',
      '  padding: 10px 14px;',
      '  border-radius: 10px;',
      '  display: flex;',
      '  align-items: center;',
      '  gap: 10px;',
      '  box-shadow: 0 4px 24px rgba(0,0,0,0.4);',
      '  animation: piqSlideUp 0.25s ease;',
      '  white-space: nowrap;',
      '}',
      '@keyframes piqSlideUp {',
      '  from { opacity:0; transform: translateX(-50%) translateY(12px); }',
      '  to   { opacity:1; transform: translateX(-50%) translateY(0); }',
      '}',
      '#piq-restore-banner .piq-label { color: #94a3b8; }',
      '#piq-restore-banner .piq-ts { color: #a78bfa; font-weight:600; }',
      '#piq-restore-btn {',
      '  background: #7c3aed; color: #fff; border: none;',
      '  padding: 5px 12px; border-radius: 6px; cursor: pointer;',
      '  font-size: 12px; font-weight: 600;',
      '  transition: background 0.12s;',
      '}',
      '#piq-restore-btn:hover { background: #6d28d9; }',
      '#piq-clear-btn {',
      '  background: transparent; color: #475569; border: none;',
      '  padding: 5px 8px; border-radius: 6px; cursor: pointer;',
      '  font-size: 12px;',
      '  transition: color 0.12s;',
      '}',
      '#piq-clear-btn:hover { color: #e2e8f0; }',
    ].join('\n');
    document.head.appendChild(s);
  }

  /* ── Collect live containers ─────────────────────────── */
  function getContainers() {
    var found = {};
    TARGETS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el) found[sel] = el;
    });
    return found;
  }

  /* ── Serialise & save ────────────────────────────────── */
  function saveState() {
    var containers = getContainers();
    var data = {};
    var hasContent = false;

    Object.keys(containers).forEach(function (sel) {
      var html = containers[sel].innerHTML.trim();
      if (html.length > MIN_LEN) {
        data[sel] = html;
        hasContent = true;
      }
    });

    if (!hasContent) return;

    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ ts: Date.now(), data: data }));
    } catch (e) { /* storage full — fail silently */ }
  }

  /* ── Load saved state ────────────────────────────────── */
  function loadState() {
    try {
      var raw = localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  /* ── Clear saved state ───────────────────────────────── */
  function clearState() {
    try { localStorage.removeItem(STORE_KEY); } catch (e) {}
  }

  /* ── Restore content into containers ─────────────────── */
  function restoreState(saved) {
    var containers = getContainers();
    Object.keys(saved.data).forEach(function (sel) {
      if (containers[sel]) {
        containers[sel].innerHTML = saved.data[sel];
        containers[sel].style.display = '';
        /* Re-show any PDF buttons that were hidden on load */
        var pdfBtn = document.getElementById('pdfBtn');
        if (pdfBtn) pdfBtn.style.display = 'inline-flex';
      }
    });
  }

  /* ── Human-readable age ──────────────────────────────── */
  function formatAge(ts) {
    var diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 60)   return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  /* ── Show restore banner ─────────────────────────────── */
  function showRestoreBanner(saved) {
    if (document.getElementById('piq-restore-banner')) return;
    injectStyles();

    var banner = document.createElement('div');
    banner.id = 'piq-restore-banner';
    banner.innerHTML =
      '<span class="piq-label">📂 Saved analysis · </span>' +
      '<span class="piq-ts">' + formatAge(saved.ts) + '</span>' +
      '<button id="piq-restore-btn">↩ Restore</button>' +
      '<button id="piq-clear-btn" title="Discard saved results">✕</button>';

    document.body.appendChild(banner);

    document.getElementById('piq-restore-btn').onclick = function () {
      restoreState(saved);
      banner.remove();
    };

    document.getElementById('piq-clear-btn').onclick = function () {
      clearState();
      banner.remove();
    };

    /* Auto-dismiss */
    setTimeout(function () {
      if (banner.parentNode) {
        banner.style.transition = 'opacity 0.4s';
        banner.style.opacity = '0';
        setTimeout(function () { if (banner.parentNode) banner.remove(); }, 400);
      }
    }, BANNER_TTL);
  }

  /* ── Watch containers with MutationObserver ──────────── */
  function setupObservers() {
    var containers = getContainers();
    Object.keys(containers).forEach(function (sel) {
      var observer = new MutationObserver(function () {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(saveState, SAVE_WAIT);
      });
      observer.observe(containers[sel], {
        childList: true,
        subtree: true,
        characterData: true
      });
    });
  }

  /* ── Init ────────────────────────────────────────────── */
  function init() {
    if (SKIP_PAGES.indexOf(page) !== -1) return;

    var saved = loadState();
    if (saved && saved.data && Object.keys(saved.data).length > 0) {
      /* Slight delay so the page's own JS finishes its init */
      setTimeout(function () { showRestoreBanner(saved); }, 900);
    }

    setupObservers();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
