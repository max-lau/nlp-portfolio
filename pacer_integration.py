"""
pacer_integration.py
====================
PACER (Public Access to Court Electronic Records) Integration
  + CourtListener free API as fallback

Features:
  • PACER session auth (username/password → token)
  • Case search by case number or party name
  • Docket entry listing
  • Document download (PDF → text extraction)
  • Auto-feed results into the NLP pipeline (sentiment, risk, timeline)
  • Auto-add analyzed docs to Case Management system

Flask Blueprint: /pacer/...

Endpoints:
  POST /pacer/login               - authenticate & store token in session
  POST /pacer/search              - search by case number or party name
  GET  /pacer/docket/<case_num>   - fetch full docket for a case
  POST /pacer/fetch_document      - download + analyze a specific document
  GET  /pacer/courts              - list available federal courts
  GET  /pacer/status              - check auth status
  GET  /pacer/courtlistener/search - free CourtListener search (no auth needed)

Environment variables needed in .env:
  PACER_USERNAME=your_pacer_username
  PACER_PASSWORD=your_pacer_password
  PACER_CLIENT_CODE=your_client_code   (optional billing code)
"""

import os
import re
import json
import time
import logging
import requests
import sqlite3
import pdfplumber
import io
from datetime import datetime, timezone
from functools import wraps
from flask import Blueprint, request, jsonify, session, g

logger = logging.getLogger(__name__)

# ── Blueprint ──────────────────────────────────────────────────────────────────
pacer_bp = Blueprint("pacer", __name__, url_prefix="/pacer")

# ── Constants ──────────────────────────────────────────────────────────────────
PACER_BASE        = "https://pacer.uscourts.gov"
PACER_AUTH_URL    = f"{PACER_BASE}/services/cso-auth"
PACER_CSOB_URL    = "https://pcl.uscourts.gov/pcl/pages/search/find.jsf"   # Case Search
PACER_API_BASE    = "https://pcl.uscourts.gov/pcl-public-api/rest"         # REST API

# CourtListener (free, no auth)
CL_BASE           = "https://www.courtlistener.com/api/rest/v3"

DB_PATH           = "legal_nlp.db"
PACER_TOKEN_KEY   = "pacer_token"
PACER_TOKEN_EXP   = "pacer_token_exp"
TOKEN_TTL_SECS    = 3600   # PACER tokens valid ~1 hour


# ══════════════════════════════════════════════════════════════════════════════
# FEDERAL COURT LIST  (court_id → name)
# ══════════════════════════════════════════════════════════════════════════════

FEDERAL_COURTS = {
    # District courts — New York (most relevant for NYC law firms)
    "nysd": "S.D.N.Y. (Southern District of New York)",
    "nyed": "E.D.N.Y. (Eastern District of New York)",
    "nynd": "N.D.N.Y. (Northern District of New York)",
    "nywd": "W.D.N.Y. (Western District of New York)",
    # Other major districts
    "cacd": "C.D. Cal. (Central District of California)",
    "dcd":  "D.D.C. (District of Columbia)",
    "ilnd": "N.D. Ill. (Northern District of Illinois)",
    "txsd": "S.D. Tex. (Southern District of Texas)",
    "flsd": "S.D. Fla. (Southern District of Florida)",
    # Appellate
    "ca2":  "2nd Circuit Court of Appeals",
    "ca9":  "9th Circuit Court of Appeals",
    "cafc": "Federal Circuit",
}


# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class PACERAuth:
    """Manage PACER session token. Token cached in Flask session."""

    @staticmethod
    def login(username: str, password: str, client_code: str = "") -> dict:
        """Authenticate with PACER and return token details."""
        payload = {
            "loginId":    username,
            "password":   password,
            "clientCode": client_code,
            "redactFlag": "1",
        }
        try:
            resp = requests.post(
                PACER_AUTH_URL,
                json=payload,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # PACER returns nextGenCSO token
            token = data.get("nextGenCSO") or data.get("loginResult", {}).get("nextGenCSO")
            if not token:
                return {"success": False, "error": "No token in PACER response", "raw": data}

            return {
                "success":   True,
                "token":     token,
                "expires_at": time.time() + TOKEN_TTL_SECS,
                "username":  username,
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"PACER login failed: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def is_valid(token_data: dict) -> bool:
        if not token_data or not token_data.get("token"):
            return False
        return time.time() < token_data.get("expires_at", 0)

    @staticmethod
    def get_headers(token: str) -> dict:
        return {
            "X-NEXT-GEN-CSO": token,
            "Content-Type":   "application/json",
            "Accept":         "application/json",
        }


def pacer_token_required(f):
    """Decorator: ensures a valid PACER token exists in session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token_data = session.get("pacer_token_data")
        if not token_data or not PACERAuth.is_valid(token_data):
            return jsonify({
                "error": "PACER authentication required. POST /pacer/login first.",
                "authenticated": False,
            }), 401
        g.pacer_token = token_data["token"]
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
# PACER API WRAPPERS
# ══════════════════════════════════════════════════════════════════════════════

class PACERClient:

    def __init__(self, token: str):
        self.token   = token
        self.headers = PACERAuth.get_headers(token)
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def search_cases(self, case_number: str = "", party_name: str = "",
                     court_id: str = "nysd", date_filed_start: str = "",
                     date_filed_end: str = "", limit: int = 25) -> dict:
        """
        Search PACER Case Locator (PCL) REST API.
        Returns list of matching cases.
        """
        params = {
            "court_id":        court_id,
            "case_number":     case_number,
            "party_name":      party_name,
            "date_filed_start": date_filed_start,
            "date_filed_end":  date_filed_end,
            "max_return":      limit,
            "sort_spec":       "cs_file_date desc",
        }
        # Remove empty params
        params = {k: v for k, v in params.items() if v}

        try:
            resp = self.session.get(
                f"{PACER_API_BASE}/cases",
                params=params, timeout=20)
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except requests.exceptions.RequestException as e:
            logger.error(f"PACER case search failed: {e}")
            return {"success": False, "error": str(e)}

    def get_docket(self, court_id: str, case_id: str,
                   include_documents: bool = True) -> dict:
        """
        Fetch docket entries for a specific case.
        court_id: e.g. 'nysd'  case_id: PACER internal case ID
        """
        params = {"dkt_entries_include": "true" if include_documents else "false"}
        try:
            resp = self.session.get(
                f"{PACER_API_BASE}/cases/{court_id}/{case_id}/docket-entries",
                params=params, timeout=30)
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except requests.exceptions.RequestException as e:
            logger.error(f"PACER docket fetch failed: {e}")
            return {"success": False, "error": str(e)}

    def download_document(self, court_id: str, case_id: str,
                          doc_id: str, seq_no: str = "0") -> dict:
        """
        Download a PACER document (PDF).
        Returns raw bytes + metadata.
        NOTE: Charges $0.10/page — use sparingly.
        """
        try:
            url = (f"{PACER_API_BASE}/cases/{court_id}/{case_id}/"
                   f"docket-entries/{doc_id}/documents/{seq_no}")
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            return {
                "success":      True,
                "content":      resp.content,
                "content_type": resp.headers.get("Content-Type", ""),
                "doc_id":       doc_id,
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"PACER document download failed: {e}")
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# COURTLISTENER  (free fallback — no auth required)
# ══════════════════════════════════════════════════════════════════════════════

class CourtListenerClient:
    """
    Free public API from Free Law Project.
    No credentials needed; rate-limited at ~5000 req/day.
    https://www.courtlistener.com/help/api/rest/
    """

    BASE = CL_BASE

    def search_opinions(self, query: str, court: str = "",
                        filed_after: str = "", limit: int = 10) -> dict:
        """Search published court opinions."""
        params = {
            "q":           query,
            "type":        "o",      # opinions
            "order_by":    "score desc",
            "court":       court,
            "filed_after": filed_after,
            "page_size":   limit,
            "format":      "json",
        }
        params = {k: v for k, v in params.items() if v}
        try:
            resp = requests.get(f"{self.BASE}/search/",
                                params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "count": data.get("count", 0),
                    "results": data.get("results", [])}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": str(e)}

    def get_docket(self, docket_id: int) -> dict:
        """Fetch a specific docket by CourtListener docket ID."""
        try:
            resp = requests.get(f"{self.BASE}/dockets/{docket_id}/",
                                params={"format": "json"}, timeout=15)
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": str(e)}

    def search_dockets(self, case_name: str = "", docket_number: str = "",
                       court: str = "nysd", limit: int = 10) -> dict:
        """Search for dockets by case name or docket number."""
        params = {
            "q":             case_name or docket_number,
            "type":          "r",    # docket (RECAP)
            "order_by":      "score desc",
            "court":         court,
            "docket_number": docket_number,
            "page_size":     limit,
            "format":        "json",
        }
        params = {k: v for k, v in params.items() if v}
        try:
            resp = requests.get(f"{self.BASE}/search/",
                                params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "count": data.get("count", 0),
                    "results": data.get("results", [])}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": str(e)}

    def get_opinion_text(self, opinion_id: int) -> dict:
        """Fetch full text of a court opinion."""
        try:
            resp = requests.get(f"{self.BASE}/opinions/{opinion_id}/",
                                params={"format": "json"}, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            # Try plain_text first, then html_with_citations
            text = (data.get("plain_text") or
                    re.sub(r"<[^>]+>", " ", data.get("html_with_citations", "")) or
                    data.get("html", ""))
            return {"success": True, "text": text.strip(), "meta": data}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# PDF TEXT EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def pdf_to_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                txt = page.extract_text() or ""
                pages.append(txt)
            return "\n".join(pages).strip()
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# NLP PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_nlp_pipeline(text: str, document_name: str) -> dict:
    """
    Send extracted text through the existing NLP pipeline.
    Calls the local Flask API endpoints that are already running.
    Returns: {sentiment, risk_score, events, entities, summary}
    """
    BASE = "http://localhost:5000"   # adjust if your Flask runs on different port
    results = {
        "sentiment":    None,
        "risk_score":   None,
        "events":       [],
        "entities":     [],
        "summary":      "",
        "language":     "en",
    }

    # 1. Sentiment analysis
    try:
        resp = requests.post(f"{BASE}/analyze",
                             json={"text": text[:5000]}, timeout=30)
        if resp.ok:
            d = resp.json()
            results["sentiment"] = d.get("sentiment", {}).get("label")
            results["language"]  = d.get("language", "en")
    except Exception as e:
        logger.warning(f"Sentiment endpoint failed: {e}")

    # 2. Timeline / event extraction
    try:
        resp = requests.post(f"{BASE}/extract_timeline",
                             json={"text": text}, timeout=30)
        if resp.ok:
            results["events"] = resp.json().get("events", [])
    except Exception as e:
        logger.warning(f"Timeline endpoint failed: {e}")

    # 3. Criminal risk scorer
    try:
        resp = requests.post(f"{BASE}/risk_score",
                             json={"text": text[:8000]}, timeout=30)
        if resp.ok:
            results["risk_score"] = resp.json().get("risk_score")
    except Exception as e:
        logger.warning(f"Risk endpoint failed: {e}")

    # 4. Named entity extraction
    try:
        resp = requests.post(f"{BASE}/entities",
                             json={"text": text[:8000]}, timeout=30)
        if resp.ok:
            results["entities"] = resp.json().get("entities", [])
    except Exception as e:
        logger.warning(f"Entity endpoint failed: {e}")

    # 5. Summarization
    try:
        resp = requests.post(f"{BASE}/summarize",
                             json={"text": text[:12000]}, timeout=60)
        if resp.ok:
            results["summary"] = resp.json().get("summary", "")
    except Exception as e:
        logger.warning(f"Summarize endpoint failed: {e}")

    return results


def add_to_case(case_id: int, document_name: str,
                doc_text: str, nlp: dict,
                source: str = "pacer",
                pacer_doc_id: str = "",
                pacer_seq_no: str = "") -> bool:
    """Persist analyzed document directly into case_documents table."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT INTO case_documents
              (case_id, document_name, source, doc_text, sentiment, risk_score,
               events_json, entities_json, summary, language,
               pacer_doc_id, pacer_seq_no)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            case_id, document_name, source,
            doc_text,
            nlp.get("sentiment"),
            nlp.get("risk_score"),
            json.dumps(nlp.get("events", [])),
            json.dumps(nlp.get("entities", [])),
            nlp.get("summary", ""),
            nlp.get("language", "en"),
            pacer_doc_id, pacer_seq_no,
        ))
        # Re-compute case risk
        docs = conn.execute(
            "SELECT risk_score FROM case_documents WHERE case_id=?",
            (case_id,)).fetchall()
        scores = [d[0] for d in docs if d[0] is not None]
        avg = sum(scores) / len(scores) if scores else None
        if avg is not None:
            risk = "high" if avg >= 7 else "medium" if avg >= 4 else "low"
            conn.execute(
                "UPDATE cases SET risk_level=?, updated_at=? WHERE id=?",
                (risk, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                 case_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"add_to_case failed: {e}")
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES — PACER
# ══════════════════════════════════════════════════════════════════════════════

@pacer_bp.route("/login", methods=["POST"])
def pacer_login():
    """
    Body: { username, password, client_code (optional) }
    Or omit body to use PACER_USERNAME / PACER_PASSWORD from environment.
    """
    data     = request.get_json(force=True) or {}
    username = (data.get("username") or
                os.environ.get("PACER_USERNAME", ""))
    password = (data.get("password") or
                os.environ.get("PACER_PASSWORD", ""))
    client_code = (data.get("client_code") or
                   os.environ.get("PACER_CLIENT_CODE", ""))

    if not username or not password:
        return jsonify({
            "error": "Provide username/password in body or set "
                     "PACER_USERNAME/PACER_PASSWORD env vars"}), 400

    result = PACERAuth.login(username, password, client_code)
    if result["success"]:
        session["pacer_token_data"] = result
        return jsonify({
            "success": True,
            "message": "PACER authentication successful",
            "expires_at": result["expires_at"],
            "username": result["username"],
        })
    return jsonify({"success": False, "error": result["error"]}), 401


@pacer_bp.route("/status", methods=["GET"])
def pacer_status():
    token_data = session.get("pacer_token_data")
    if token_data and PACERAuth.is_valid(token_data):
        return jsonify({
            "authenticated": True,
            "username":      token_data.get("username"),
            "expires_at":    token_data.get("expires_at"),
            "seconds_left":  int(token_data.get("expires_at", 0) - time.time()),
        })
    return jsonify({"authenticated": False})


@pacer_bp.route("/courts", methods=["GET"])
def list_courts():
    return jsonify({"courts": FEDERAL_COURTS})


@pacer_bp.route("/search", methods=["POST"])
@pacer_token_required
def pacer_search():
    """
    Body: { case_number, party_name, court_id, date_filed_start,
            date_filed_end, limit }
    """
    data   = request.get_json(force=True)
    client = PACERClient(g.pacer_token)
    result = client.search_cases(
        case_number     = data.get("case_number", ""),
        party_name      = data.get("party_name", ""),
        court_id        = data.get("court_id", "nysd"),
        date_filed_start= data.get("date_filed_start", ""),
        date_filed_end  = data.get("date_filed_end", ""),
        limit           = int(data.get("limit", 25)),
    )
    return jsonify(result)


@pacer_bp.route("/docket/<court_id>/<case_id>", methods=["GET"])
@pacer_token_required
def get_docket(court_id, case_id):
    """
    Fetch full docket for a case.
    Optional query param: include_documents=true/false
    """
    include_docs = request.args.get("include_documents", "true").lower() == "true"
    client = PACERClient(g.pacer_token)
    result = client.get_docket(court_id, case_id, include_docs)
    return jsonify(result)


@pacer_bp.route("/fetch_document", methods=["POST"])
@pacer_token_required
def fetch_document():
    """
    Download a PACER document, extract text, run NLP, optionally add to case.
    Body: {
        court_id*, case_id*, doc_id*, seq_no,
        case_management_id,   ← if set, auto-adds to this case
        run_nlp               ← default true
    }
    """
    data     = request.get_json(force=True)
    required = ["court_id", "case_id", "doc_id"]
    for f in required:
        if not data.get(f):
            return jsonify({"error": f"Missing: {f}"}), 400

    client = PACERClient(g.pacer_token)
    dl     = client.download_document(
        court_id = data["court_id"],
        case_id  = data["case_id"],
        doc_id   = data["doc_id"],
        seq_no   = data.get("seq_no", "0"),
    )
    if not dl["success"]:
        return jsonify(dl), 502

    # Extract text from PDF
    text = pdf_to_text(dl["content"])
    if not text:
        return jsonify({"error": "Could not extract text from document"}), 422

    response_data = {
        "success":    True,
        "doc_id":     data["doc_id"],
        "text_chars": len(text),
        "preview":    text[:500],
    }

    # Run NLP pipeline
    if data.get("run_nlp", True):
        doc_name = (data.get("document_name") or
                    f"PACER_{data['court_id']}_{data['case_id']}_{data['doc_id']}")
        nlp = run_nlp_pipeline(text, doc_name)
        response_data["nlp"] = {k: v for k, v in nlp.items()
                                if k not in ("events", "entities")}
        response_data["nlp"]["event_count"]  = len(nlp.get("events", []))
        response_data["nlp"]["entity_count"] = len(nlp.get("entities", []))

        # Add to case management if requested
        case_mgmt_id = data.get("case_management_id")
        if case_mgmt_id:
            ok = add_to_case(
                case_id      = int(case_mgmt_id),
                document_name= doc_name,
                doc_text     = text,
                nlp          = nlp,
                source       = "pacer",
                pacer_doc_id = data["doc_id"],
                pacer_seq_no = data.get("seq_no", "0"),
            )
            response_data["added_to_case"] = ok

    return jsonify(response_data)


# ══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES — COURTLISTENER (free fallback)
# ══════════════════════════════════════════════════════════════════════════════

@pacer_bp.route("/courtlistener/search", methods=["GET"])
def cl_search():
    """
    No auth required. Query params: q, court, filed_after, limit, type
    type: opinions (default) | dockets
    """
    q          = request.args.get("q", "").strip()
    court      = request.args.get("court", "nysd")
    filed_after= request.args.get("filed_after", "")
    limit      = min(25, int(request.args.get("limit", 10)))
    search_type= request.args.get("type", "opinions")

    if not q:
        return jsonify({"error": "Query param 'q' required"}), 400

    cl = CourtListenerClient()
    if search_type == "dockets":
        result = cl.search_dockets(
            case_name=q, court=court, limit=limit)
    else:
        result = cl.search_opinions(
            query=q, court=court, filed_after=filed_after, limit=limit)

    return jsonify(result)


@pacer_bp.route("/courtlistener/opinion/<int:opinion_id>", methods=["GET"])
def cl_opinion(opinion_id):
    """
    Fetch full opinion text + optionally run NLP + add to case.
    Query params: case_management_id, run_nlp (default true)
    """
    cl     = CourtListenerClient()
    result = cl.get_opinion_text(opinion_id)
    if not result["success"]:
        return jsonify(result), 502

    text = result["text"]
    response = {
        "success":    True,
        "opinion_id": opinion_id,
        "text_chars": len(text),
        "preview":    text[:500],
        "meta": {
            "case_name":    result["meta"].get("cluster", {}).get("case_name", ""),
            "court":        result["meta"].get("cluster", {}).get("docket", {}).get("court_id", ""),
            "date_filed":   result["meta"].get("cluster", {}).get("date_filed", ""),
        }
    }

    run_nlp      = request.args.get("run_nlp", "true").lower() == "true"
    case_mgmt_id = request.args.get("case_management_id")

    if run_nlp and text:
        doc_name = (response["meta"].get("case_name") or
                    f"CourtListener_Opinion_{opinion_id}")
        nlp = run_nlp_pipeline(text, doc_name)
        response["nlp"] = {k: v for k, v in nlp.items()
                           if k not in ("events", "entities")}
        response["nlp"]["event_count"]  = len(nlp.get("events", []))
        response["nlp"]["entity_count"] = len(nlp.get("entities", []))

        if case_mgmt_id:
            ok = add_to_case(
                case_id      = int(case_mgmt_id),
                document_name= doc_name,
                doc_text     = text,
                nlp          = nlp,
                source       = "pacer",
            )
            response["added_to_case"] = ok

    return jsonify(response)


@pacer_bp.route("/courtlistener/docket/<int:docket_id>", methods=["GET"])
def cl_docket(docket_id):
    cl     = CourtListenerClient()
    result = cl.get_docket(docket_id)
    return jsonify(result)


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

def register(app):
    """
    Call from app.py:
        from pacer_integration import register as register_pacer
        register_pacer(app)

    Also add to requirements.txt:
        pdfplumber
        requests
    """
    if not app.secret_key:
        app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-me-in-prod")
    app.register_blueprint(pacer_bp)
    print("[PACER] Blueprint registered at /pacer ✓")
    print("[PACER] CourtListener (free) available at /pacer/courtlistener/search")
    print("[PACER] Set PACER_USERNAME / PACER_PASSWORD in .env for full PACER access")
