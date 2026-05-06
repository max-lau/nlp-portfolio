#!/usr/bin/env python3
"""
patch_persist.py — ParaIQ Session 4: Analysis Persistence
Injects paraiq-persist.js into all 21 HTML pages.

Run from VPS after patch_sidebar.py has already run:
  cd /root/nlp-portfolio/frontend/demo1
  python3 patch_persist.py
"""

import os
import glob

FRONTEND_DIR = '/root/nlp-portfolio/frontend/demo1'
HTML_FILES   = sorted(glob.glob(os.path.join(FRONTEND_DIR, '*.html')))

JS_INJECT = '  <script src="paraiq-persist.js"></script>'

def patch_file(fpath):
    fname = os.path.basename(fpath)

    with open(fpath, 'r', encoding='utf-8') as f:
        html = f.read()

    if 'paraiq-persist.js' in html:
        print(f'—   {fname}  (already patched)')
        return False

    if '</body>' not in html:
        print(f'⚠️   {fname}  (no </body> tag — skipping)')
        return False

    # Inject just before </body>
    html = html.replace('</body>', JS_INJECT + '\n</body>', 1)

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'✅  {fname}')
    return True

def main():
    if not HTML_FILES:
        print(f'ERROR: No HTML files found in {FRONTEND_DIR}')
        return

    print(f'Patching {len(HTML_FILES)} HTML files...\n')
    patched = sum(1 for f in HTML_FILES if patch_file(f))

    print(f'\n{"─"*50}')
    print(f'Done. {patched}/{len(HTML_FILES)} files updated.')
    print('\nNext steps:')
    print('  pm2 restart paraiq-frontend')
    print('  Test: open analyzer.html, run an analysis, navigate away, come back')
    print('  You should see: "📂 Saved analysis · Xs ago  [↩ Restore] [✕]"')

if __name__ == '__main__':
    main()
