"""
patch_auth.py
Run on VPS: python3 patch_auth.py
Does everything in one shot:
  1. Adds X-API-Key middleware to main.py
  2. Adds PARAIQ_KEY constant to all HTML files
  3. Updates all fetch() calls to include the X-API-Key header
"""

import os
import re
import glob

API_KEY = os.getenv('PARAIQ_API_KEY', '')
if not API_KEY:
    # Read from .env if not in environment
    env_path = '/root/nlp-portfolio/.env'
    for line in open(env_path):
        if line.startswith('PARAIQ_API_KEY='):
            API_KEY = line.strip().split('=', 1)[1]
            break

if not API_KEY:
    print("ERROR — PARAIQ_API_KEY not found in .env")
    exit(1)

print(f"Using key: {API_KEY[:8]}...{API_KEY[-4:]}")

# ── 1. PATCH main.py ──────────────────────────────────────────────────────────

MAIN_PATH = '/root/nlp-portfolio/backend/demo1/main.py'
content = open(MAIN_PATH).read()

if 'APIKeyMiddleware' in content:
    print("main.py — middleware already present, skipping")
else:
    # Add import for Request and Response after existing imports
    old_import = 'from fastapi import FastAPI, HTTPException, Query'
    new_import = 'from fastapi import FastAPI, HTTPException, Query, Request\nfrom fastapi.responses import JSONResponse\nfrom starlette.middleware.base import BaseHTTPMiddleware'
    content = content.replace(old_import, new_import)

    # Add middleware class before app = FastAPI(...)
    old_app = 'app = FastAPI(title="NLP Text Analyzer API")'
    middleware_code = '''# ── API Key Auth Middleware ───────────────────────────────────────────────────

PARAIQ_API_KEY = os.getenv("PARAIQ_API_KEY", "")

EXEMPT_PATHS = {"/health", "/openapi.json", "/docs", "/redoc", "/favicon.ico"}
EXEMPT_PREFIXES = ("/docs/", "/redoc/")

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Always allow OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)
        # Allow exempt paths
        path = request.url.path
        if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)
        # Check key
        key = request.headers.get("X-API-Key", "")
        if not PARAIQ_API_KEY or key != PARAIQ_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"}
            )
        return await call_next(request)

'''
    content = content.replace(old_app, middleware_code + old_app)

    # Add middleware to app — insert after app = FastAPI line
    old_add = 'app.include_router(intake_router'
    new_add = 'app.add_middleware(APIKeyMiddleware)\napp.include_router(intake_router'
    content = content.replace(old_add, new_add)

    open(MAIN_PATH, 'w').write(content)
    print("main.py — APIKeyMiddleware added ✅")

# Verify
content = open(MAIN_PATH).read()
print(f"main.py — APIKeyMiddleware present: {'APIKeyMiddleware' in content}")

# ── 2. PATCH HTML FILES ───────────────────────────────────────────────────────

html_files = glob.glob('/root/nlp-portfolio/frontend/demo1/*.html')
print(f"\nPatching {len(html_files)} HTML files...")

KEY_CONST = f"  const PARAIQ_KEY = '{API_KEY}';"
KEY_COMMENT = "  // ParaIQ API authentication key"

updated = []
skipped = []

for fpath in sorted(html_files):
    fname = os.path.basename(fpath)
    html = open(fpath).read()

    if 'PARAIQ_KEY' in html:
        skipped.append(fname)
        continue

    # Find <script> tag and inject the key constant after it
    script_idx = html.find('<script>')
    if script_idx == -1:
        script_idx = html.find('<script\n')
    if script_idx == -1:
        skipped.append(fname + ' (no script tag)')
        continue

    insert_pos = html.find('\n', script_idx) + 1
    html = html[:insert_pos] + KEY_COMMENT + '\n' + KEY_CONST + '\n' + html[insert_pos:]

    # Update ALL fetch() calls to include X-API-Key header
    # Pattern 1: headers: { 'Content-Type': 'application/json' }
    html = html.replace(
        "headers: { 'Content-Type': 'application/json' }",
        "headers: { 'Content-Type': 'application/json', 'X-API-Key': PARAIQ_KEY }"
    )
    # Pattern 2: headers: { "Content-Type": "application/json" }
    html = html.replace(
        'headers: { "Content-Type": "application/json" }',
        'headers: { "Content-Type": "application/json", "X-API-Key": PARAIQ_KEY }'
    )
    # Pattern 3: multi-line headers with Content-Type
    html = re.sub(
        r"('Content-Type':\s*'application/json')\s*\n(\s*\})",
        r"'Content-Type': 'application/json',\n        'X-API-Key': PARAIQ_KEY\n        }",
        html
    )

    open(fpath, 'w').write(html)
    updated.append(fname)

print(f"\nUpdated  ({len(updated)}): {', '.join(updated)}")
print(f"Skipped  ({len(skipped)}): {', '.join(skipped)}")

# ── 3. VERIFY ─────────────────────────────────────────────────────────────────

print("\n── Verification ──")
sample_files = ['interrogation.html', 'credibility.html', 'deposition.html', 'compare.html']
for fname in sample_files:
    fpath = f'/root/nlp-portfolio/frontend/demo1/{fname}'
    if os.path.exists(fpath):
        content = open(fpath).read()
        has_key = 'PARAIQ_KEY' in content
        has_header = 'X-API-Key' in content
        print(f"  {fname}: key_const={has_key} header={has_header}")

print("\nDone. Run: pm2 restart paraiq-api")
