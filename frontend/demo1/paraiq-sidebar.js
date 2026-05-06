/* ═══════════════════════════════════════════════════════════
   paraiq-sidebar.js  —  ParaIQ Sidebar Navigation
   Self-contained IIFE. No dependencies.
═══════════════════════════════════════════════════════════ */
(function () {

  /* ── Nav structure ───────────────────────────────────── */
  var GROUPS = [
    {
      label: 'Core',
      items: [
        { href: 'home.html',      label: 'Home',         icon: '🏠' },
        { href: 'dashboard.html', label: 'Dashboard',    icon: '📊' },
        { href: 'insights.html',  label: 'Insights',     icon: '💡' },
      ]
    },
    {
      label: 'Analysis',
      items: [
        { href: 'analyzer.html',  label: 'Analyzer',     icon: '🔬' },
        { href: 'batch.html',     label: 'Batch',        icon: '📦' },
        { href: 'compare.html',   label: 'Compare',      icon: '⚖️'  },
        { href: 'review.html',    label: 'Review',       icon: '📝' },
      ]
    },
    {
      label: 'Legal',
      items: [
        { href: 'interrogation.html', label: 'Interrogation', icon: '🎤' },
        { href: 'deposition.html',    label: 'Deposition',    icon: '📋' },
        { href: 'credibility.html',   label: 'Credibility',   icon: '⭐' },
        { href: 'scorer.html',        label: 'Scorer',        icon: '🎯' },
      ]
    },
    {
      label: 'Compliance',
      items: [
        { href: 'risk.html',      label: 'Risk',         icon: '⚠️'  },
        { href: 'audit.html',     label: 'Audit',        icon: '🔒' },
        { href: 'citations.html', label: 'Citations',    icon: '📚' },
        { href: 'timeline.html',  label: 'Timeline',     icon: '📅' },
      ]
    },
    {
      label: 'Processing',
      items: [
        { href: 'intake.html',           label: 'Intake',         icon: '📷' },
        { href: 'redaction.html',        label: 'Redaction',      icon: '✏️'  },
        { href: 'redaction_review.html', label: 'Redact Review',  icon: '👁️'  },
        { href: 'multilingual.html',     label: 'Multilingual',   icon: '🌐' },
        { href: 'model.html',            label: 'Model',          icon: '🤖' },
      ]
    },
  ];

  /* ── Detect active page ─────────────────────────────── */
  var currentFile = window.location.pathname.split('/').pop() || 'home.html';
  // index.html → treat as home.html for active state
  if (currentFile === 'index.html') currentFile = 'home.html';

  /* ── Build sidebar HTML ─────────────────────────────── */
  function buildNav() {
    var html = '';
    for (var g = 0; g < GROUPS.length; g++) {
      var group = GROUPS[g];
      html += '<div class="sb-group"><div class="sb-group-label">' + group.label + '</div>';
      for (var i = 0; i < group.items.length; i++) {
        var item = group.items[i];
        var active = item.href === currentFile ? ' active' : '';
        html += '<a class="sb-link' + active + '" href="' + item.href + '">' +
                '<span class="sb-icon">' + item.icon + '</span>' +
                item.label + '</a>';
      }
      html += '</div>';
    }
    return html;
  }

  /* ── Storage key ─────────────────────────────────────── */
  var STORAGE_KEY = 'paraiq_sb_open';

  /* ── Open/close state ───────────────────────────────── */
  function setOpen(open, toggle) {
    var sidebar = document.getElementById('paraiq-sidebar');
    if (!sidebar) return;
    if (open) {
      document.body.classList.add('sb-open');
      sidebar.classList.remove('sb-collapsed');
      toggle.innerHTML = '✕';
    } else {
      document.body.classList.remove('sb-open');
      sidebar.classList.add('sb-collapsed');
      toggle.innerHTML = '☰';
    }
    try { localStorage.setItem(STORAGE_KEY, open ? 'true' : 'false'); } catch (e) {}
  }

  /* ── Mount ──────────────────────────────────────────── */
  function mount() {
    /* Sidebar element */
    var sidebar = document.createElement('div');
    sidebar.id = 'paraiq-sidebar';
    sidebar.innerHTML =
      '<div class="sb-brand">' +
        '<div class="sb-brand-name">Para<span>IQ</span></div>' +
        '<div class="sb-brand-sub">NLP Legal Intelligence · Demo 1</div>' +
      '</div>' +
      '<nav class="sb-nav">' + buildNav() + '</nav>' +
      '<div class="sb-footer">' +
        '<a href="https://nlp.para-iq.com/docs" target="_blank">API Docs →</a>' +
      '</div>';

    /* Toggle button */
    var toggle = document.createElement('button');
    toggle.id = 'sb-toggle';
    toggle.title = 'Toggle navigation';
    toggle.setAttribute('aria-label', 'Toggle navigation');
    toggle.innerHTML = '☰';

    toggle.addEventListener('click', function () {
      setOpen(!document.body.classList.contains('sb-open'), toggle);
    });

    /* Close sidebar on mobile when a link is clicked */
    sidebar.addEventListener('click', function (e) {
      if (e.target.classList.contains('sb-link') && window.innerWidth < 769) {
        setOpen(false, toggle);
      }
    });

    /* Close on backdrop click (mobile) */
    document.addEventListener('click', function (e) {
      if (window.innerWidth < 769 &&
          document.body.classList.contains('sb-open') &&
          !sidebar.contains(e.target) &&
          e.target !== toggle) {
        setOpen(false, toggle);
      }
    });

    /* Insert before everything else in body */
    document.body.insertBefore(sidebar, document.body.firstChild);
    document.body.insertBefore(toggle, document.body.firstChild);

    /* Restore state from localStorage */
    var isMobile = window.innerWidth < 769;
    var stored = null;
    try { stored = localStorage.getItem(STORAGE_KEY); } catch (e) {}
    var isOpen = isMobile ? false : (stored !== 'false');
    setOpen(isOpen, toggle);
  }

  /* ── Boot ───────────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

})();
