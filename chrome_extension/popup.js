// popup.js
// NLP Legal Analyzer Chrome Extension — Popup Logic

const DEFAULT_API = "http://localhost:8000";

// ── State ──────────────────────────────────────────────────────────────────────
let apiBase = DEFAULT_API;

// ── Init ───────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  // Load saved settings
  const stored = await chrome.storage.local.get(["apiUrl", "selectedText", "pendingAction"]);
  if (stored.apiUrl) {
    apiBase = stored.apiUrl;
    document.getElementById("apiUrl").value = stored.apiUrl;
  }

  // Auto-fill selected text
  if (stored.selectedText) {
    document.getElementById("analyzeText").value   = stored.selectedText;
    document.getElementById("riskText").value      = stored.selectedText;
    document.getElementById("citationsText").value = stored.selectedText;
    document.getElementById("timelineText").value  = stored.selectedText;

    // Auto-trigger pending action from context menu
    if (stored.pendingAction === "nlp-risk") switchTab("risk");
    if (stored.pendingAction === "nlp-citations") switchTab("citations");

    await chrome.storage.local.remove(["selectedText", "pendingAction"]);
  }

  // Check API status
  checkApiStatus();

  // Tab switching
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  // Analyze tab
  document.getElementById("pasteBtn").addEventListener("click", pasteSelected);
  document.getElementById("analyzeBtn").addEventListener("click", runAnalyze);

  // Risk tab
  document.getElementById("riskBtn").addEventListener("click", runRisk);

  // Citations tab
  document.getElementById("extractCitationsBtn").addEventListener("click", () => runCitations(false));
  document.getElementById("resolveCitationsBtn").addEventListener("click", () => runCitations(true));

  // Timeline tab
  document.getElementById("timelineBtn").addEventListener("click", runTimeline);

  // Settings
  document.getElementById("saveSettingsBtn").addEventListener("click", saveSettings);
  document.getElementById("testApiBtn").addEventListener("click", testConnection);
});

// ── Helpers ────────────────────────────────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.dataset.tab === name)
  );
  document.querySelectorAll(".tab-content").forEach(c => {
    c.style.display = c.id === `tab-${name}` ? "block" : "none";
  });
}

function showLoading(containerId) {
  document.getElementById(containerId).innerHTML = `
    <div class="loading">
      <div class="spinner"></div>
      Analyzing...
    </div>`;
}

function showError(containerId, msg) {
  document.getElementById(containerId).innerHTML =
    `<div class="error">⚠ ${msg}</div>`;
}

async function apiFetch(path, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(`${apiBase}${path}`, opts);
  if (!resp.ok) throw new Error(`API error ${resp.status}`);
  return resp.json();
}

async function pasteSelected() {
  const stored = await chrome.storage.local.get("selectedText");
  if (stored.selectedText) {
    document.getElementById("analyzeText").value = stored.selectedText;
  }
}

async function checkApiStatus() {
  const dot = document.getElementById("statusDot");
  try {
    await apiFetch("/health");
    dot.style.background = "#4caf7d";
    dot.title = "API Connected";
  } catch {
    dot.style.background = "#e05252";
    dot.title = "API Offline";
  }
}

function riskColor(level) {
  return { critical: "#e05252", high: "#e8a030", medium: "#f0c040", low: "#4caf7d", minimal: "#5b7fa6" }[level] || "#7a7670";
}

function entityClass(type) {
  const map = { PERSON: "tag-PERSON", ORG: "tag-ORG", GPE: "tag-GPE",
    STATUTE: "tag-STATUTE", JUDGE: "tag-JUDGE", LEGAL_TERM: "tag-LEGAL_TERM", DOCKET: "tag-DOCKET" };
  return map[type] || "tag-default";
}

// ── Analyze ────────────────────────────────────────────────────────────────────

async function runAnalyze() {
  const text = document.getElementById("analyzeText").value.trim();
  if (!text) return;

  showLoading("analyzeResults");
  document.getElementById("analyzeBtn").disabled = true;

  try {
    // Run entities + custom entities in parallel
    const [entResult, customResult] = await Promise.all([
      apiFetch("/entities/score", "POST", { text }),
      apiFetch("/entities/custom/extract", "POST", { text }),
    ]);

    const entities    = entResult.entities || [];
    const customEnts  = customResult.entities || [];
    const allEntities = [...entities, ...customEnts];

    let html = "";

    // Entities section
    if (allEntities.length > 0) {
      html += `<div class="section-title">Entities (${allEntities.length})</div>`;
      html += `<div class="entity-grid">`;
      allEntities.slice(0, 20).forEach(e => {
        html += `<span class="entity-tag ${entityClass(e.type)}" title="${e.type}${e.confidence ? ' · ' + Math.round(e.confidence*100) + '%' : ''}">${e.text}</span>`;
      });
      html += `</div>`;
    }

    // Summary
    const summary = entResult.summary || {};
    if (summary.avg_confidence) {
      html += `<div class="section-title">Summary</div>`;
      html += `<div style="font-size:11px;color:#b8b4aa;line-height:1.8;">
        Avg Confidence: <strong style="color:#e8e4da">${Math.round(summary.avg_confidence*100)}%</strong> &nbsp;·&nbsp;
        Entities: <strong style="color:#e8e4da">${summary.total_entities}</strong>
      </div>`;
    }

    document.getElementById("analyzeResults").innerHTML = html || `<div class="empty">No entities found</div>`;

  } catch (err) {
    showError("analyzeResults", err.message);
  } finally {
    document.getElementById("analyzeBtn").disabled = false;
  }
}

// ── Risk ───────────────────────────────────────────────────────────────────────

async function runRisk() {
  const text    = document.getElementById("riskText").value.trim();
  const context = document.getElementById("riskContext").value;
  if (!text) return;

  showLoading("riskResults");
  document.getElementById("riskBtn").disabled = true;

  try {
    const data  = await apiFetch("/risk/score", "POST", { text, context, label: "Selection" });
    const color = riskColor(data.level);
    const pct   = (data.score / 10) * 100;

    let html = `
      <div class="section-title">Risk Score</div>
      <div class="risk-row">
        <div class="risk-score" style="color:${color}">${data.score}</div>
        <div>
          <div class="risk-level" style="color:${color}">${data.level}</div>
          <div style="font-size:9px;color:#7a7670;">out of 10</div>
        </div>
      </div>
      <div class="risk-bar-wrap">
        <div class="risk-bar" style="width:${pct}%;background:${color}"></div>
      </div>`;

    const breakdown = data.category_breakdown || {};
    if (Object.keys(breakdown).length) {
      html += `<div class="section-title">Breakdown</div>`;
      Object.entries(breakdown).sort((a,b)=>b[1]-a[1]).forEach(([cat, val]) => {
        html += `<div style="display:flex;justify-content:space-between;font-size:11px;padding:3px 0;color:#b8b4aa;">
          <span>${cat.replace(/_/g,' ')}</span>
          <span style="color:#e8e4da;font-weight:600">${val}</span>
        </div>`;
      });
    }

    const signals = data.top_signals || [];
    if (signals.length) {
      html += `<div class="section-title">Top Signals</div>`;
      signals.slice(0,4).forEach(s => {
        html += `<div style="font-size:10px;color:#b8b4aa;padding:2px 0;">
          • <strong style="color:#e8e4da">${s.signal}</strong>
          <span style="color:#7a7670"> (${s.category})</span>
        </div>`;
      });
    }

    document.getElementById("riskResults").innerHTML = html;

  } catch (err) {
    showError("riskResults", err.message);
  } finally {
    document.getElementById("riskBtn").disabled = false;
  }
}

// ── Citations ──────────────────────────────────────────────────────────────────

async function runCitations(resolve) {
  const text = document.getElementById("citationsText").value.trim();
  if (!text) return;

  showLoading("citationsResults");

  try {
    const endpoint = resolve ? "/citations/resolve" : "/citations/extract";
    const data = await apiFetch(endpoint, "POST", { text, resolve });
    const citations = data.citations || [];

    if (!citations.length) {
      document.getElementById("citationsResults").innerHTML =
        `<div class="empty">No legal citations found</div>`;
      return;
    }

    let html = `<div class="section-title">Citations (${citations.length})</div>`;
    citations.forEach(c => {
      const topMatch = c.resolved?.top_match;
      html += `<div class="citation-item">
        <div class="citation-raw">${c.raw}</div>
        <div class="citation-type">${c.label}</div>
        ${topMatch ? `<div class="citation-resolved">↳ ${topMatch.case_name} · ${topMatch.court || ''}</div>` : ""}
      </div>`;
    });

    const summary = data.summary || {};
    html += `<div style="font-size:10px;color:#7a7670;padding-top:4px;">
      ${summary.total_citations} citation(s) · ${summary.resolved || 0} resolved
    </div>`;

    document.getElementById("citationsResults").innerHTML = html;

  } catch (err) {
    showError("citationsResults", err.message);
  }
}

// ── Timeline ───────────────────────────────────────────────────────────────────

async function runTimeline() {
  const text = document.getElementById("timelineText").value.trim();
  if (!text) return;

  showLoading("timelineResults");
  document.getElementById("timelineBtn").disabled = true;

  try {
    const data   = await apiFetch("/timeline", "POST", { text });
    const events = data.events || [];

    if (!events.length) {
      document.getElementById("timelineResults").innerHTML =
        `<div class="empty">No timeline events found</div>`;
      return;
    }

    let html = `<div class="section-title">${data.title || "Timeline"} (${events.length})</div>`;
    events.forEach(e => {
      html += `<div class="timeline-item">
        <div class="timeline-date">${e.date}</div>
        <div class="timeline-event">${e.event}</div>
        ${e.parties?.length ? `<div style="font-size:9px;color:#7a7670;margin-top:2px;">${e.parties.join(", ")}</div>` : ""}
      </div>`;
    });

    document.getElementById("timelineResults").innerHTML = html;

  } catch (err) {
    showError("timelineResults", err.message);
  } finally {
    document.getElementById("timelineBtn").disabled = false;
  }
}

// ── Settings ───────────────────────────────────────────────────────────────────

async function saveSettings() {
  const url = document.getElementById("apiUrl").value.trim();
  apiBase = url;
  await chrome.storage.local.set({ apiUrl: url });
  document.getElementById("settingsResult").innerHTML =
    `<div style="color:#4caf7d;font-size:11px;">✓ Settings saved</div>`;
  checkApiStatus();
}

async function testConnection() {
  const url = document.getElementById("apiUrl").value.trim();
  const res = document.getElementById("settingsResult");
  res.innerHTML = `<div style="color:#7a7670;font-size:11px;">Testing...</div>`;
  try {
    const resp = await fetch(`${url}/health`);
    const data = await resp.json();
    res.innerHTML = `<div style="color:#4caf7d;font-size:11px;">✓ Connected — API online</div>`;
  } catch {
    res.innerHTML = `<div style="color:#e05252;font-size:11px;">✗ Cannot reach API at ${url}</div>`;
  }
}
