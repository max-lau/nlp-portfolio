"""
app_integration_snippet.py
===========================
Add these lines to your existing app.py to activate Case Management + PACER.
"""

# ── At the top of app.py ──────────────────────────────────────────────────────
from case_management  import register as register_cases
from pacer_integration import register as register_pacer

# ── After app = Flask(__name__) ───────────────────────────────────────────────
register_cases(app)   # mounts /cases/...
register_pacer(app)   # mounts /pacer/...


# ── .env additions ────────────────────────────────────────────────────────────
"""
PACER_USERNAME=your_pacer_username
PACER_PASSWORD=your_pacer_password
PACER_CLIENT_CODE=                   # optional billing code, can be blank
FLASK_SECRET_KEY=some-long-random-string
"""


# ── requirements.txt additions ────────────────────────────────────────────────
"""
pdfplumber>=0.10.0        # PDF text extraction for PACER documents
requests>=2.31.0          # already likely installed
"""


# ── Quick test (from terminal, with Flask running) ────────────────────────────
"""
# Create a case
curl -X POST http://localhost:5000/cases/create \
  -H 'Content-Type: application/json' \
  -d '{"case_number":"1:24-cr-00142","client_name":"United States v. Chen",
       "court":"S.D.N.Y.","status":"open","tags":["criminal","federal"]}'

# List cases
curl http://localhost:5000/cases/list

# Add a document
curl -X POST http://localhost:5000/cases/1/add_document \
  -H 'Content-Type: application/json' \
  -d '{"document_name":"Criminal Complaint","doc_text":"On January 15, 2024, defendant..."}'

# Timeline
curl http://localhost:5000/cases/1/timeline

# Search all cases
curl 'http://localhost:5000/cases/search?q=conspiracy'

# CourtListener (no auth needed)
curl 'http://localhost:5000/pacer/courtlistener/search?q=wire+fraud+SDNY&court=nysd&type=opinions'

# PACER login (needs real account)
curl -X POST http://localhost:5000/pacer/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_USER","password":"YOUR_PASS"}'
"""
