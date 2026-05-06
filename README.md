# ParaIQ — NLP Legal Intelligence Platform

AI-powered legal document analysis platform built with FastAPI, Python, and Claude AI.
Designed for law firms, in-house counsel, and compliance teams to review contracts,
extract obligations, identify risk, and accelerate legal workflows.

**Live:** [https://app.para-iq.com](https://app.para-iq.com) · **API:** [https://nlp.para-iq.com](https://nlp.para-iq.com)

---

## Modules (21 pages)

| Module | Description |
|--------|-------------|
| **Analyzer** | Sentiment analysis, named entity recognition, keyword extraction |
| **Batch** | Bulk document analysis with CSV export |
| **Timeline** | Chronological event extraction from legal documents |
| **Dashboard** | Case management — create, track, and export case files |
| **Insights** | Aggregate analytics across all stored analyses |
| **Scorer** | NLP scoring across multiple dimensions |
| **Risk** | Multi-category risk scoring with signal breakdown |
| **Citations** | US Code, Federal Reporter, Westlaw citation extraction + CourtListener resolution |
| **Compare** | Document similarity — cosine, Jaccard, entity overlap, citation diff, structural |
| **Model** | Fine-tuned model management |
| **Audit** | Full audit trail of all API activity |
| **Intake** | OCR from photo/scan → text extraction + NLP analysis |
| **Redaction** | PII and sensitive entity redaction |
| **Redaction Review** | Review and approve redacted documents |
| **Interrogation** | Deposition transcript analysis — diarization, contradiction detection, evasion flagging |
| **Credibility** | Witness credibility scoring across 5 dimensions with radar chart |
| **Deposition** | Deposition summary generation |
| **Multilingual** | NLP analysis in 13 languages |
| **Review** | Document review workflow |

---

## Tech Stack

- **Backend:** Python 3.12, FastAPI, Uvicorn, SQLite
- **NLP / AI:** Anthropic Claude API (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`)
- **PDF Export:** ReportLab
- **OCR:** Tesseract / Google Vision
- **Frontend:** Vanilla HTML/CSS/JavaScript (21 pages)
- **Infrastructure:** Hetzner VPS, Cloudflare Tunnel, pm2

---

## Project Structure

```
nlp-portfolio/
├── backend/
│   └── demo1/
│       ├── main.py                  # FastAPI app — core NLP endpoints
│       ├── pdf_export.py            # Analysis, risk, case, intake PDF export
│       ├── pdf_module_export.py     # Generic /export/module endpoint
│       ├── pdf_utils.py             # Shared ReportLab utilities
│       ├── interrogation_export.py  # Interrogation PDF export
│       ├── document_comparison.py   # Document similarity router
│       ├── risk_scorer.py           # Multi-category risk scoring
│       ├── citation_resolver.py     # Legal citation extraction
│       ├── case_management.py       # Case CRUD + documents
│       ├── audit_trail.py           # Request audit middleware
│       ├── auth.py                  # JWT authentication
│       ├── multilingual.py          # 13-language NLP analysis
│       ├── ocr_intake.py            # OCR intake pipeline
│       └── analyses.db              # SQLite database
├── frontend/
│   └── demo1/                       # 21 HTML pages
│       ├── paraiq-sidebar.css/js    # Shared sidebar navigation
│       ├── paraiq-persist.js        # Analysis result persistence
│       ├── paraiq-export.js         # PDF export utility
│       └── *.html                   # Module pages
├── .env                             # API keys (not committed)
├── requirements.txt
└── README.md
```

---

## API Endpoints

### Core Analysis
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/analyze` | Sentiment, NER, keywords — saved to SQLite |
| POST | `/batch` | Bulk document analysis |
| POST | `/timeline` | Event extraction |
| GET | `/stats` | Aggregate statistics |

### Legal Modules
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/risk/score` | Multi-category risk scoring |
| POST | `/documents/compare` | Document similarity analysis |
| POST | `/documents/lease-diff` | Lease clause comparison (AI) |
| POST | `/citations/extract` | Legal citation extraction |
| POST | `/interrogate` | Transcript analysis |
| POST | `/credibility/score` | Witness credibility scoring |

### PDF Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/export/analysis` | Analysis result PDF |
| POST | `/export/risk` | Risk report PDF |
| POST | `/export/intake` | Intake report PDF |
| POST | `/export/module` | Generic module PDF (all other modules) |
| GET | `/export/case/{id}` | Case summary PDF |

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get JWT token |
| GET | `/auth/me` | Current user info |

All endpoints require `X-API-Key` header.

---

## Quick Start

### 1. Clone and set up environment

```bash
git clone https://github.com/max-lau/nlp-portfolio.git
cd nlp-portfolio
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Add your keys to .env:
# ANTHROPIC_API_KEY=...
# PARAIQ_API_KEY=...
```

### 3. Run the API

```bash
uvicorn backend.demo1.main:app --host 0.0.0.0 --port 5003
```

### 4. Serve the frontend

```bash
cd frontend/demo1
python3 -m http.server 8080
# Open http://localhost:8080/home.html
```

---

## Frontend Features

- **Sidebar navigation** — fixed 220px sidebar across all 21 pages, grouped by module category, mobile-responsive with hamburger toggle
- **Analysis persistence** — results auto-saved to localStorage, restore banner on return visit
- **PDF export** — floating export button on all modules, structured ReportLab output with KV tables, data tables, and bullet sections

---

## Author

Maxwell L. — [GitHub](https://github.com/max-lau)
