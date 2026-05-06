/* ═══════════════════════════════════════════════════════════
   paraiq-export.js  —  ParaIQ Session 5: Unified PDF Export
   Shared frontend utility for all module export buttons.

   Usage (per page):
     ParaIQExport.download({
       module: 'credibility',
       title:  'Credibility Report',
       sections: [ ... ]
     });

   Or use the auto-packager for standard result containers:
     ParaIQExport.autoExport('credibility', 'Credibility Report');
═══════════════════════════════════════════════════════════ */

var ParaIQExport = (function () {

  /* ── Config ─────────────────────────────────────────── */
  var API = 'https://nlp.para-iq.com';

  /* Resolve API key — tries multiple locations pages might use */
  function getApiKey() {
    if (typeof API_KEY !== 'undefined' && API_KEY) return API_KEY;
    if (typeof PARAIQ_KEY !== 'undefined' && PARAIQ_KEY) return PARAIQ_KEY;
    try { return localStorage.getItem('paraiq_api_key') || ''; } catch (e) {}
    return '';
  }

  /* ── Button state helpers ───────────────────────────── */
  function setBtnLoading(btn) {
    if (!btn) return;
    btn._origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '⏳ Generating PDF…';
  }

  function resetBtn(btn) {
    if (!btn) return;
    btn.disabled = false;
    btn.innerHTML = btn._origText || '📄 Export PDF';
  }

  /* ── Core download ──────────────────────────────────── */
  async function download(config, btnEl) {
    var btn = btnEl || document.getElementById('paraiq-export-btn');
    setBtnLoading(btn);

    try {
      var resp = await fetch(API + '/export/module', {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key':    getApiKey()
        },
        body: JSON.stringify(config)
      });

      if (!resp.ok) {
        var err = await resp.text();
        throw new Error('Server error: ' + err);
      }

      var blob = await resp.blob();
      var url  = URL.createObjectURL(blob);
      var a    = document.createElement('a');
      a.href   = url;
      a.download = (config.filename ||
        config.module + '_report_' + new Date().toISOString().slice(0, 10) + '.pdf');
      document.body.appendChild(a);
      a.click();
      setTimeout(function () {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 500);

    } catch (e) {
      console.error('[ParaIQExport]', e);
      alert('PDF export failed: ' + e.message);
    } finally {
      resetBtn(btn);
    }
  }

  /* ── DOM helpers ────────────────────────────────────── */

  /** Extract rows from an HTML table element */
  function tableToRows(tbl) {
    if (!tbl) return { headers: [], rows: [] };
    var allRows = Array.from(tbl.querySelectorAll('tr'));
    if (allRows.length === 0) return { headers: [], rows: [] };
    var headers = Array.from(allRows[0].querySelectorAll('th,td'))
                       .map(function (c) { return c.innerText.trim(); });
    var rows = allRows.slice(1).map(function (tr) {
      return Array.from(tr.querySelectorAll('td,th'))
                  .map(function (c) { return c.innerText.trim(); });
    });
    return { headers: headers, rows: rows };
  }

  /** Convert a results container's DOM into PDF sections */
  function domToSections(containerSel) {
    var container = document.querySelector(containerSel);
    if (!container || container.innerHTML.trim().length < 50) return null;

    var sections = [];

    /* Walk top-level children and group by heading */
    var currentHeading = null;
    var currentItems   = [];

    function flush() {
      if (currentItems.length === 0) return;
      var text = currentItems.join('\n').trim();
      if (text.length > 0) {
        sections.push({ type: 'text', heading: currentHeading, content: text });
      }
      currentItems   = [];
      currentHeading = null;
    }

    function walk(el) {
      var tag = el.tagName ? el.tagName.toLowerCase() : '';

      if (/^h[1-6]$/.test(tag) || el.classList.contains('section-title') ||
          el.classList.contains('card-title') || el.classList.contains('result-card-header')) {
        flush();
        currentHeading = el.innerText.trim();
        return;
      }

      if (tag === 'table') {
        flush();
        var t = tableToRows(el);
        if (t.headers.length > 0) {
          sections.push({ type: 'table', heading: currentHeading, headers: t.headers, rows: t.rows });
          currentHeading = null;
        }
        return;
      }

      if (tag === 'ul' || tag === 'ol') {
        flush();
        var items = Array.from(el.querySelectorAll('li')).map(function (li) {
          return li.innerText.trim();
        }).filter(Boolean);
        if (items.length) {
          sections.push({ type: 'bullets', heading: currentHeading, items: items });
          currentHeading = null;
        }
        return;
      }

      /* Generic text nodes */
      var text = el.innerText ? el.innerText.trim() : '';
      if (text.length > 3) currentItems.push(text);

      /* Recurse into containers */
      if (el.children && el.children.length > 0 &&
          !['p','span','a','strong','em','b','i'].includes(tag)) {
        Array.from(el.children).forEach(walk);
      }
    }

    Array.from(container.children).forEach(walk);
    flush();

    return sections.length > 0 ? sections : null;
  }

  /* ── Auto-export (generic DOM scrape) ───────────────── */
  function autoExport(module, title, btnEl) {
    /* Try known result containers in priority order */
    var selectors = ['#results', '#pdfResults', '#textResults',
                     '.results-grid', '#redactionPanel'];
    var sections = null;
    for (var i = 0; i < selectors.length; i++) {
      sections = domToSections(selectors[i]);
      if (sections) break;
    }

    if (!sections || sections.length === 0) {
      alert('No results to export. Run an analysis first.');
      return;
    }

    download({
      module:    module,
      title:     title,
      subtitle:  new Date().toLocaleDateString('en-US', { year:'numeric', month:'long', day:'numeric' }),
      sections:  sections,
    }, btnEl);
  }

  /* ── Per-module packagers ────────────────────────────── */

  var modules = {

    batch: function (btn) {
      /* Batch analysis — table of results */
      var sections = domToSections('#results') || domToSections('.results-table-wrap');
      if (!sections) { alert('Run batch analysis first.'); return; }
      download({ module:'batch', title:'Batch Analysis Report', sections:sections }, btn);
    },

    timeline: function (btn) {
      var sections = domToSections('#results');
      if (!sections) { alert('Generate a timeline first.'); return; }
      download({ module:'timeline', title:'Legal Event Timeline', sections:sections }, btn);
    },

    citations: function (btn) {
      var sections = domToSections('#results');
      if (!sections) { alert('Run citation extraction first.'); return; }
      download({ module:'citations', title:'Citation Resolution Report', sections:sections }, btn);
    },

    compare: function (btn) {
      /* Read structured data from specific DOM elements */
      var sections = [];

      /* 1. Similarity Scores */
      var cosine   = (document.getElementById('cosineScore')   || {}).textContent || '';
      var jaccard  = (document.getElementById('jaccardScore')  || {}).textContent || '';
      var combined = (document.getElementById('combinedScore') || {}).textContent || '';
      var simLabel = (document.getElementById('simLabel')      || {}).textContent || '';
      if (cosine) {
        sections.push({ type: 'kv', heading: 'Similarity Scores', data: [
          ['Cosine (TF-IDF)', cosine],
          ['Jaccard (Terms)', jaccard],
          ['Combined Score',  combined],
          ['Assessment',      simLabel.toUpperCase()],
        ]});
      }

      /* 2. Entity Overlap */
      var overlapScore = (document.getElementById('overlapScore') || {}).textContent || '';
      var shared = Array.from(document.querySelectorAll('#sharedEnts .tag')).map(function(e){ return e.textContent.trim(); });
      var onlyA  = Array.from(document.querySelectorAll('#onlyA .tag')).map(function(e){ return e.textContent.trim(); });
      var onlyB  = Array.from(document.querySelectorAll('#onlyB .tag')).map(function(e){ return e.textContent.trim(); });
      if (overlapScore) {
        sections.push({ type: 'kv', heading: 'Entity Overlap', data: [
          ['Overlap Score', overlapScore],
          ['Shared Entities', shared.length ? shared.join(', ') : 'None'],
          ['Only in Document A', onlyA.length ? onlyA.join(', ') : 'None'],
          ['Only in Document B', onlyB.length ? onlyB.join(', ') : 'None'],
        ]});
      }

      /* 3. Citation Diff */
      var citEl = document.getElementById('citationDiff');
      if (citEl && citEl.innerText.trim()) {
        sections.push({ type: 'text', heading: 'Citation Diff', content: citEl.innerText.trim() });
      }

      /* 4. Structural Comparison — read table cells */
      var structEl = document.getElementById('structGrid');
      if (structEl) {
        var cells = Array.from(structEl.querySelectorAll('.struct-cell')).map(function(c){ return c.innerText.trim(); });
        // cells layout: [METRIC, DOC A, DOC B, Words, val, val, Sentences, val, val, ...]
        var structRows = [];
        var i = 3; // skip header row (3 cells)
        while (i + 2 < cells.length) {
          structRows.push([cells[i], cells[i+1], cells[i+2]]);
          i += 3;
        }
        if (structRows.length) {
          sections.push({ type: 'table', heading: 'Structural Comparison',
            headers: ['Metric', 'Document A', 'Document B'],
            rows: structRows,
            col_widths_in: [2.5, 1.9, 1.9]
          });
        }
      }

      /* 5. Lease Clause Analysis (if visible) */
      var leaseCard = document.getElementById('leaseCard');
      if (leaseCard && leaseCard.style.display !== 'none') {
        var keyTerms = Array.from(document.querySelectorAll('#leaseKeyTerms .lease-tag')).map(function(e){ return e.textContent.trim(); });
        var modified = Array.from(document.querySelectorAll('#leaseModified .clause-item')).map(function(e){ return e.innerText.trim(); });
        var added    = Array.from(document.querySelectorAll('#leaseAdded .clause-item')).map(function(e){ return e.innerText.trim(); });
        var removed  = Array.from(document.querySelectorAll('#leaseRemoved .clause-item')).map(function(e){ return e.innerText.trim(); });
        if (keyTerms.length || modified.length) {
          if (keyTerms.length) sections.push({ type: 'bullets', heading: 'Lease Key Term Changes', items: keyTerms });
          if (modified.length) sections.push({ type: 'bullets', heading: 'Modified Clauses', items: modified });
          if (added.length)    sections.push({ type: 'bullets', heading: 'Added Clauses',    items: added });
          if (removed.length)  sections.push({ type: 'bullets', heading: 'Removed Clauses',  items: removed });
        }
      }

      if (!sections.length) { alert('Run document comparison first.'); return; }
      download({ module:'compare', title:'Document Comparison Report', sections:sections }, btn);
    },

    credibility: function (btn) {
      /* Credibility has radar chart + dimension scores */
      var sections = domToSections('#results');
      /* Also try to capture dimension table if separate */
      var extra = domToSections('.radar-labels') || domToSections('.dimension-scores');
      if (extra) sections = (sections || []).concat(extra);
      if (!sections || sections.length === 0) { alert('Score a witness first.'); return; }
      download({ module:'credibility', title:'Witness Credibility Report', sections:sections }, btn);
    },

    deposition: function (btn) {
      var sections = domToSections('#results');
      if (!sections) { alert('Generate a deposition summary first.'); return; }
      download({ module:'deposition', title:'Deposition Summary Report', sections:sections }, btn);
    },

    scorer: function (btn) {
      var sections = domToSections('#results');
      if (!sections) { alert('Run scoring first.'); return; }
      download({ module:'scorer', title:'NLP Scoring Report', sections:sections }, btn);
    },

    audit: function (btn) {
      var sections = domToSections('#results') || domToSections('.results-table-wrap');
      if (!sections) { alert('Load audit data first.'); return; }
      download({ module:'audit', title:'Audit Trail Report', sections:sections }, btn);
    },

    multilingual: function (btn) {
      var sections = domToSections('#results');
      if (!sections) { alert('Run multilingual analysis first.'); return; }
      download({ module:'multilingual', title:'Multilingual NLP Report', sections:sections }, btn);
    },

    review: function (btn) {
      var sections = domToSections('#results');
      if (!sections) { alert('Complete document review first.'); return; }
      download({ module:'review', title:'Document Review Report', sections:sections }, btn);
    },

    redaction: function (btn) {
      var sections = domToSections('#pdfResults') || domToSections('#redactionPanel');
      if (!sections) { alert('Run redaction analysis first.'); return; }
      download({ module:'redaction', title:'Redaction Report', sections:sections }, btn);
    },

    redaction_review: function (btn) {
      var sections = domToSections('#results') || domToSections('#redactionPanel');
      if (!sections) { alert('Load redaction review first.'); return; }
      download({ module:'redaction_review', title:'Redaction Review Report', sections:sections }, btn);
    },

  };

  /* ── Inject export button ───────────────────────────── */

  function injectButton(module, label) {
    if (document.getElementById('paraiq-export-btn')) return;

    var btn = document.createElement('button');
    btn.id          = 'paraiq-export-btn';
    btn.innerHTML   = '📄 ' + (label || 'Export PDF');
    btn.title       = 'Download results as PDF';
    btn.onclick     = function () {
      if (modules[module]) {
        modules[module](btn);
      } else {
        autoExport(module, label || 'Report', btn);
      }
    };

    /* Style — matches ParaIQ button aesthetic */
    var s = btn.style;
    s.position       = 'fixed';
    s.bottom         = '24px';
    s.right          = '24px';
    s.zIndex         = '8888';
    s.background     = '#7c3aed';
    s.color          = '#fff';
    s.border         = 'none';
    s.borderRadius   = '10px';
    s.padding        = '10px 18px';
    s.fontSize       = '13px';
    s.fontWeight     = '600';
    s.cursor         = 'pointer';
    s.boxShadow      = '0 4px 16px rgba(124,58,237,0.4)';
    s.fontFamily     = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    s.transition     = 'background 0.15s, transform 0.1s';

    btn.addEventListener('mouseover',  function () { s.background = '#6d28d9'; });
    btn.addEventListener('mouseout',   function () { s.background = '#7c3aed'; });
    btn.addEventListener('mousedown',  function () { s.transform  = 'scale(0.97)'; });
    btn.addEventListener('mouseup',    function () { s.transform  = 'scale(1)'; });

    document.body.appendChild(btn);
  }

  /* ── Public API ─────────────────────────────────────── */
  return {
    download:     download,
    autoExport:   autoExport,
    injectButton: injectButton,
    modules:      modules,
    domToSections: domToSections,
  };

})();
