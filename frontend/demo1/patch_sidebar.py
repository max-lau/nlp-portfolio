#!/usr/bin/env python3
"""
patch_sidebar.py — ParaIQ Session 3
Injects sidebar nav across all 21 HTML pages.

What it does per file:
  1. Removes old .nav / .nav-* CSS lines from <style> block
  2. Removes <nav class="nav">...</nav> block
  3. Injects <link rel="stylesheet" href="paraiq-sidebar.css"> in <head>
  4. Injects <script src="paraiq-sidebar.js"></script> before </body>

Run from VPS:
  cd /root/nlp-portfolio/frontend/demo1
  python3 patch_sidebar.py
"""

import re
import os
import glob

FRONTEND_DIR = '/root/nlp-portfolio/frontend/demo1'
HTML_FILES   = sorted(glob.glob(os.path.join(FRONTEND_DIR, '*.html')))

CSS_INJECT = '  <link rel="stylesheet" href="paraiq-sidebar.css">'
JS_INJECT  = '  <script src="paraiq-sidebar.js"></script>'

# CSS lines to drop — any line whose stripped form starts with one of these
NAV_CSS_PREFIXES = (
    '.nav {',
    '.nav-brand {',
    '.nav-brand span {',
    '.nav-sub {',
    '.nav-links {',
    '.nav-link {',
    '.nav-link:hover {',
    '.nav-link.active {',
)

# ── Per-file patch ────────────────────────────────────────────────────────────

def patch_file(fpath):
    fname = os.path.basename(fpath)

    with open(fpath, 'r', encoding='utf-8') as f:
        html = f.read()

    original = html
    changes  = []

    # 1. Remove nav CSS lines inside <style> blocks
    style_blocks = re.findall(r'(<style[^>]*>)(.*?)(</style>)', html, re.DOTALL)
    for tag_open, content, tag_close in style_blocks:
        lines = content.split('\n')
        cleaned = []
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(p) for p in NAV_CSS_PREFIXES):
                changes.append(f'  css removed: {stripped[:70]}')
            else:
                cleaned.append(line)
        new_content = '\n'.join(cleaned)
        if new_content != content:
            html = html.replace(tag_open + content + tag_close,
                                tag_open + new_content + tag_close, 1)

    # 2. Remove <nav class="nav">...</nav> block (including leading whitespace/newline)
    nav_pattern = re.compile(r'\n?\s*<nav class="nav">.*?</nav>', re.DOTALL)
    html_new, n = nav_pattern.subn('', html)
    if n:
        changes.append(f'  removed <nav class="nav"> block')
        html = html_new

    # 3. Inject CSS link before </head> (skip if already present)
    if 'paraiq-sidebar.css' not in html:
        html = html.replace('</head>', CSS_INJECT + '\n</head>', 1)
        changes.append('  injected paraiq-sidebar.css')

    # 4. Inject JS before </body> (skip if already present)
    if 'paraiq-sidebar.js' not in html:
        html = html.replace('</body>', JS_INJECT + '\n</body>', 1)
        changes.append('  injected paraiq-sidebar.js')

    # 5. Write if changed
    if html != original:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'✅  {fname}')
        for c in changes:
            print(c)
    else:
        print(f'—   {fname}  (no changes needed)')

    return html != original

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not HTML_FILES:
        print(f'ERROR: No HTML files found in {FRONTEND_DIR}')
        return

    print(f'Patching {len(HTML_FILES)} HTML files in {FRONTEND_DIR}\n')
    patched = 0
    for fpath in HTML_FILES:
        if patch_file(fpath):
            patched += 1

    print(f'\n{"─"*50}')
    print(f'Done. {patched}/{len(HTML_FILES)} files updated.')
    print('\nNext steps:')
    print('  pm2 restart paraiq-frontend')
    print('  Open: https://app.para-iq.com/home.html')

if __name__ == '__main__':
    main()
