#!/usr/bin/env python3
"""
patch_pdf_export.py — ParaIQ Session 5: Unified PDF Export
Injects paraiq-export.js + floating export button into pages
that don't already have a working PDF export.

Run from VPS after patch_sidebar.py and patch_persist.py:
  cd /root/nlp-portfolio/frontend/demo1
  python3 patch_pdf_export.py
"""

import os
import re
import glob

FRONTEND_DIR = '/root/nlp-portfolio/frontend/demo1'
HTML_FILES   = sorted(glob.glob(os.path.join(FRONTEND_DIR, '*.html')))

# ── Per-page config ─────────────────────────────────────────────────────────
# Pages that already have their own exportPDF() — skip button injection
# (the button is already hardcoded in HTML), but still inject the JS file.
ALREADY_HAVE_BUTTON = {
    'intake.html',           # hardcoded "📄 Download Intake Report as PDF"
    'interrogation.html',    # has interrogation_export.py endpoint
}

# Pages where we inject the floating button + auto-packager
# module key → must match a key in ParaIQExport.modules OR falls back to autoExport
MODULE_MAP = {
    'analyzer.html':          ('analyzer',         'Export Analysis PDF'),
    'batch.html':             ('batch',             'Export Batch PDF'),
    'timeline.html':          ('timeline',          'Export Timeline PDF'),
    'citations.html':         ('citations',         'Export Citations PDF'),
    'compare.html':           ('compare',           'Export Comparison PDF'),
    'credibility.html':       ('credibility',       'Export Credibility PDF'),
    'deposition.html':        ('deposition',        'Export Deposition PDF'),
    'scorer.html':            ('scorer',            'Export Scoring PDF'),
    'audit.html':             ('audit',             'Export Audit PDF'),
    'multilingual.html':      ('multilingual',      'Export Multilingual PDF'),
    'review.html':            ('review',            'Export Review PDF'),
    'redaction.html':         ('redaction',         'Export Redaction PDF'),
    'redaction_review.html':  ('redaction_review',  'Export Redact Review PDF'),
}

# Pages to skip entirely (no results to export)
SKIP_PAGES = {'home.html', 'dashboard.html', 'insights.html', 'index.html', 'model.html'}

JS_FILE_TAG = '  <script src="paraiq-export.js"></script>'

def make_button_snippet(module: str, label: str) -> str:
    """Return an inline <script> that injects the export button on DOMContentLoaded."""
    return (
        f'\n  <script>\n'
        f'  document.addEventListener("DOMContentLoaded", function() {{\n'
        f'    if (typeof ParaIQExport !== "undefined") {{\n'
        f'      ParaIQExport.injectButton("{module}", "{label}");\n'
        f'    }}\n'
        f'  }});\n'
        f'  </script>\n'
    )

def patch_file(fpath: str) -> bool:
    fname = os.path.basename(fpath)

    if fname in SKIP_PAGES:
        print(f'—   {fname}  (skipped — no results)')
        return False

    with open(fpath, 'r', encoding='utf-8') as f:
        html = f.read()

    original = html
    changes  = []

    # 1. Inject paraiq-export.js script tag before </body> (always, to make
    #    the utility available even on pages with hardcoded buttons)
    if 'paraiq-export.js' not in html:
        html = html.replace('</body>', JS_FILE_TAG + '\n</body>', 1)
        changes.append('  injected paraiq-export.js')

    # 2. Inject the injectButton() call for pages in MODULE_MAP
    #    (skip if the page already has its own button)
    if fname in MODULE_MAP and fname not in ALREADY_HAVE_BUTTON:
        module, label = MODULE_MAP[fname]
        marker = f'ParaIQExport.injectButton("{module}"'
        if marker not in html:
            snippet = make_button_snippet(module, label)
            html = html.replace('</body>', snippet + '</body>', 1)
            changes.append(f'  injected export button — module={module}')

    if html != original:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'✅  {fname}')
        for c in changes:
            print(c)
        return True
    else:
        print(f'—   {fname}  (no changes needed)')
        return False


# ── main.py patch ────────────────────────────────────────────────────────────

MAIN_PY = '/root/nlp-portfolio/backend/demo1/main.py'

MODULE_IMPORT = 'from backend.demo1.pdf_module_export import router as module_pdf_router'
MODULE_MOUNT  = 'app.include_router(module_pdf_router, prefix="/export", tags=["PDF Export"])'

def patch_main_py():
    if not os.path.exists(MAIN_PY):
        print(f'\n⚠️  main.py not found at {MAIN_PY} — skip backend patch')
        print(f'   Add manually:\n     {MODULE_IMPORT}\n     {MODULE_MOUNT}')
        return

    with open(MAIN_PY, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content
    changes  = []

    if MODULE_IMPORT not in content:
        # Insert after last existing pdf import
        content = content.replace(
            'from backend.demo1.pdf_export import router as pdf_router',
            'from backend.demo1.pdf_export import router as pdf_router\n' + MODULE_IMPORT,
            1
        )
        changes.append('  added module_pdf_router import')

    if MODULE_MOUNT not in content:
        # Insert after existing pdf_router include
        content = content.replace(
            'app.include_router(pdf_router, prefix="/export", tags=["PDF Export"])',
            'app.include_router(pdf_router, prefix="/export", tags=["PDF Export"])\n' + MODULE_MOUNT,
            1
        )
        changes.append('  mounted module_pdf_router at /export/module')

    if content != original:
        with open(MAIN_PY, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'\n✅  main.py patched')
        for c in changes:
            print(c)
    else:
        print(f'\n—   main.py (router already mounted)')


# ── Entry ────────────────────────────────────────────────────────────────────

def main():
    print(f'Patching {len(HTML_FILES)} HTML files for PDF export...\n')
    patched = sum(1 for f in HTML_FILES if patch_file(f))

    patch_main_py()

    print(f'\n{"─"*52}')
    print(f'HTML: {patched} file(s) updated')
    print('\nNext steps:')
    print('  1. SCP pdf_utils.py and pdf_module_export.py to:')
    print('       /root/nlp-portfolio/backend/demo1/')
    print('  2. pm2 restart mirofish  (or your Flask/FastAPI backend process)')
    print('  3. pm2 restart paraiq-frontend')
    print('  4. Test: open compare.html → run analysis → click purple "Export PDF" button')

if __name__ == '__main__':
    main()
