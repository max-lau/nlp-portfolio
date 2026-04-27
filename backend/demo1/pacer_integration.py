"""
pacer_integration.py
====================
FastAPI APIRouter: PACER + CourtListener Court Integration

Register in main.py:
    from backend.demo1.pacer_integration import router as pacer_router
    app.include_router(pacer_router, prefix="/pacer", tags=["PACER"])

Add to .env:
    PACER_USERNAME=your_username
    PACER_PASSWORD=your_password
    PACER_TEST_MODE=true          # blocks downloads, caps results to 3
    PACER_MAX_PAGES=3             # max PDF pages extracted (cost control)

Endpoints:
  POST /pacer/login                           - authenticate with PACER
  GET  /pacer/status                          - auth status + test mode info
  GET  /pacer/courts                          - list federal courts
  POST /pacer/search                          - search PACER cases (auth required)
  GET  /pacer/docket/{court_id}/{case_id}     - fetch docket entries (auth required)
  POST /pacer/fetch_document                  - download + analyze doc (auth required)
  GET  /pacer/courtlistener/search            - free CourtListener search (no auth)
  GET  /pacer/courtlistener/opinion/{id}      - fetch + analyze opinion (no auth)
  GET  /pacer/courtlistener/docket/{id}       - fetch docket via CourtListener
"""

import os
import re
import json
import time
import logging
import sqlite3
import io
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
import requests

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logging.warning("[PACER] pdfplumber not installed — PDF extraction disabled. Run: pip install pdfplumber")

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Constants ──────────────────────────────────────────────────────────────────
PACER_BASE     = "https://pacer.uscourts.gov"
PACER_AUTH_URL = f"{PACER_BASE}/services/cso-auth"
PACER_API_BASE = "https://pcl.uscourts.gov/pcl-public-api/rest"
CL_BASE        = "https://www.courtlistener.com/api/rest/v3"
DB_PATH        = "analyses.db"
TOKEN_TTL_SECS = 3600

# ── CourtListener token (free at courtlistener.com/profile/api/) ───────────────
CL_API_KEY = os.environ.get("COURTLISTENER_API_KEY", "")

def cl_headers() -> dict:
    h = {"Accept": "application/json"}
    key = os.environ.get("COURTLISTENER_API_KEY", "")
    if key:
        h["Authorization"] = f"Token {key}"
    return h

# ── Test mode (set in .env) ────────────────────────────────────────────────────
PACER_TEST_MODE = os.environ.get("PACER_TEST_MODE", "true").lower() == "true"
PACER_MAX_PAGES = int(os.environ.get("PACER_MAX_PAGES", "3"))

FEDERAL_COURTS = {
    "nysd": "S.D.N.Y. (Southern District of New York)",
    "nyed": "E.D.N.Y. (Eastern District of New York)",
    "nynd": "N.D.N.Y. (Northern District of New York)",
    "nywd": "W.D.N.Y. (Western District of New York)",
    "cacd": "C.D. Cal. (Central District of California)",
    "dcd":  "D.D.C. (District of Columbia)",
    "ilnd": "N.D. Ill. (Northern District of Illinois)",
    "txsd": "S.D. Tex. (Southern District of Texas)",
    "flsd": "S.D. Fla. (Southern District of Florida)",
    "ca2":  "2nd Circuit Court of Appeals",
    "ca9":  "9th Circuit Court of Appeals",
}

# ── Simple in-memory token store (keyed by username) ──────────────────────────
_token_store: dict = {}


# ══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ══════════════════════════════════════════════════════════════════════════════

class LoginBody(BaseModel):
    username:    Optional[str] = None
    password:    Optional[str] = None
    client_code: Optional[str] = ""

class PACERSearchBody(BaseModel):
    case_number:      Optional[str] = ""
    party_name:       Optional[str] = ""
    court_id:         Optional[str] = "nysd"
    date_filed_start: Optional[str] = ""
    date_filed_end:   Optional[str] = ""
    limit:            Optional[int] = 10

class FetchDocBody(BaseModel):
    court_id:           str
    case_id:            str
    doc_id:             str
    seq_no:             Optional[str] = "0"
    document_name:      Optional[str] = None
    run_nlp:            Optional[bool] = True
    case_management_id: Optional[int] = None


# ══════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def pacer_login_request(username: str, password: str, client_code: str = "") -> dict:
    try:
        resp = requests.post(PACER_AUTH_URL, json={
            "loginId": username, "password": password,
            "clientCode": client_code, "redactFlag": "1",
        }, headers={"Content-Type": "application/json",
                    "Accept": "application/json"}, timeout=15)
        resp.raise_for_status()
        data  = resp.json()
        token = data.get("nextGenCSO") or \
                data.get("loginResult", {}).get("nextGenCSO")
        if not token:
            return {"success": False, "error": "No token in PACER response"}
        return {"success": True, "token": token,
                "expires_at": time.time() + TOKEN_TTL_SECS,
                "username": username}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_token(username: str) -> Optional[str]:
    data = _token_store.get(username)
    if data and time.time() < data.get("expires_at", 0):
        return data["token"]
    return None


def require_pacer_token(username: str) -> str:
    token = get_token(username)
    if not token:
        raise HTTPException(401,
            "PACER authentication required. POST /pacer/login first.")
    return token


def pacer_headers(token: str) -> dict:
    return {"X-NEXT-GEN-CSO": token,
            "Content-Type": "application/json",
            "Accept": "application/json"}


# ══════════════════════════════════════════════════════════════════════════════
# PDF EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def pdf_to_text(pdf_bytes: bytes) -> str:
    if not PDF_AVAILABLE:
        return "[pdfplumber not installed — run: pip install pdfplumber]"
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = pdf.pages[:PACER_MAX_PAGES]
            if len(pdf.pages) > PACER_MAX_PAGES:
                logger.info(f"[PACER] PDF truncated to {PACER_MAX_PAGES}/{len(pdf.pages)} pages")
            return "\n".join(p.extract_text() or "" for p in pages).strip()
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# NLP PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

def run_nlp_pipeline(text: str) -> dict:
    """
    Call the existing FastAPI NLP endpoints running on the same server.
    Adjust BASE_URL if running on a different port.
    """
    BASE = "http://localhost:8000"
    results = {"sentiment": None, "risk_score": None,
                "events": [], "entities": [], "summary": "", "language": "en"}

    for endpoint, key, payload in [
        ("/analyze",           "sentiment",  {"text": text[:5000]}),
        ("/extract_timeline",  "events",     {"text": text}),
        ("/risk_score",        "risk_score", {"text": text[:8000]}),
        ("/entities",          "entities",   {"text": text[:8000]}),
        ("/summarize",         "summary",    {"text": text[:12000]}),
    ]:
        try:
            r = requests.post(f"{BASE}{endpoint}", json=payload, timeout=30)
            if r.ok:
                d = r.json()
                if key == "sentiment":
                    results["sentiment"] = d.get("sentiment", {}).get("label")
                    results["language"]  = d.get("language", "en")
                elif key == "risk_score":
                    results["risk_score"] = d.get("risk_score")
                elif key == "summary":
                    results["summary"] = d.get("summary", "")
                else:
                    results[key] = d.get(key, [])
        except Exception as e:
            logger.warning(f"NLP endpoint {endpoint} failed: {e}")

    return results


def add_to_case(case_id: int, document_name: str, doc_text: str,
                nlp: dict, source: str = "pacer",
                pacer_doc_id: str = "", pacer_seq_no: str = "") -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT INTO case_documents
              (case_id, document_name, source, doc_text, sentiment, risk_score,
               events_json, entities_json, summary, language, pacer_doc_id, pacer_seq_no)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (case_id, document_name, source, doc_text,
              nlp.get("sentiment"), nlp.get("risk_score"),
              json.dumps(nlp.get("events",[])),
              json.dumps(nlp.get("entities",[])),
              nlp.get("summary",""), nlp.get("language","en"),
              pacer_doc_id, pacer_seq_no))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"add_to_case failed: {e}")
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — AUTH
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/login")
async def pacer_login(body: LoginBody):
    username = body.username or os.environ.get("PACER_USERNAME","")
    password = body.password or os.environ.get("PACER_PASSWORD","")
    if not username or not password:
        raise HTTPException(400,
            "Provide username/password or set PACER_USERNAME/PACER_PASSWORD in .env")

    result = pacer_login_request(username, password, body.client_code or "")
    if result["success"]:
        _token_store[username] = result
        return {"success": True, "username": username,
                "expires_at": result["expires_at"],
                "test_mode": PACER_TEST_MODE,
                "max_pages": PACER_MAX_PAGES}
    raise HTTPException(401, result["error"])


@router.get("/status")
async def pacer_status():
    # Return status of first stored token (single-user assumption for now)
    for username, data in _token_store.items():
        if time.time() < data.get("expires_at", 0):
            return {"authenticated": True, "username": username,
                    "expires_at": data["expires_at"],
                    "seconds_left": int(data["expires_at"] - time.time()),
                    "test_mode": PACER_TEST_MODE,
                    "max_pages": PACER_MAX_PAGES}
    return {"authenticated": False,
            "test_mode": PACER_TEST_MODE,
            "max_pages": PACER_MAX_PAGES}


@router.get("/courts")
async def list_courts():
    return {"courts": FEDERAL_COURTS}


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — PACER (auth required)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/search")
async def pacer_search(body: PACERSearchBody):
    # Find any valid token in store
    token = None
    for username in _token_store:
        token = get_token(username)
        if token: break
    if not token:
        raise HTTPException(401, "PACER authentication required. POST /pacer/login first.")

    limit = min(body.limit, 3) if PACER_TEST_MODE else body.limit

    params = {k: v for k, v in {
        "court_id":         body.court_id,
        "case_number":      body.case_number,
        "party_name":       body.party_name,
        "date_filed_start": body.date_filed_start,
        "date_filed_end":   body.date_filed_end,
        "max_return":       limit,
        "sort_spec":        "cs_file_date desc",
    }.items() if v}

    try:
        resp = requests.get(f"{PACER_API_BASE}/cases",
                            params=params,
                            headers=pacer_headers(token), timeout=20)
        resp.raise_for_status()
        result = {"success": True, "data": resp.json()}
        if PACER_TEST_MODE:
            result["test_mode"] = True
            result["note"] = "Results capped at 3. Downloads blocked. Set PACER_TEST_MODE=false to lift limits."
        return result
    except Exception as e:
        raise HTTPException(502, f"PACER search failed: {e}")


@router.get("/docket/{court_id}/{case_id}")
async def get_docket(court_id: str, case_id: str,
                     include_documents: bool = Query(True)):
    token = None
    for username in _token_store:
        token = get_token(username)
        if token: break
    if not token:
        raise HTTPException(401, "PACER authentication required.")

    try:
        resp = requests.get(
            f"{PACER_API_BASE}/cases/{court_id}/{case_id}/docket-entries",
            params={"dkt_entries_include": str(include_documents).lower()},
            headers=pacer_headers(token), timeout=30)
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}
    except Exception as e:
        raise HTTPException(502, f"PACER docket fetch failed: {e}")


@router.post("/fetch_document")
async def fetch_document(body: FetchDocBody):
    if PACER_TEST_MODE:
        raise HTTPException(403,
            "Document download blocked in test mode (PACER_TEST_MODE=true). "
            "Set PACER_TEST_MODE=false in .env to enable.")

    token = None
    for username in _token_store:
        token = get_token(username)
        if token: break
    if not token:
        raise HTTPException(401, "PACER authentication required.")

    try:
        url  = (f"{PACER_API_BASE}/cases/{body.court_id}/{body.case_id}/"
                f"docket-entries/{body.doc_id}/documents/{body.seq_no}")
        resp = requests.get(url, headers=pacer_headers(token), timeout=60)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"PACER document download failed: {e}")

    text = pdf_to_text(resp.content)
    if not text:
        raise HTTPException(422, "Could not extract text from document")

    response = {"success": True, "doc_id": body.doc_id,
                "text_chars": len(text), "preview": text[:500]}

    if body.run_nlp:
        doc_name = (body.document_name or
                    f"PACER_{body.court_id}_{body.case_id}_{body.doc_id}")
        nlp = run_nlp_pipeline(text)
        response["nlp"] = {k: v for k, v in nlp.items()
                           if k not in ("events","entities")}
        response["nlp"]["event_count"]  = len(nlp.get("events",[]))
        response["nlp"]["entity_count"] = len(nlp.get("entities",[]))

        if body.case_management_id:
            ok = add_to_case(body.case_management_id, doc_name, text, nlp,
                             pacer_doc_id=body.doc_id, pacer_seq_no=body.seq_no)
            response["added_to_case"] = ok

    return response


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES — COURTLISTENER (free, no auth)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/courtlistener/search")
async def cl_search(
    q:           str           = Query(...),
    court:       Optional[str] = Query("nysd"),
    filed_after: Optional[str] = Query(""),
    limit:       int           = Query(10, le=25),
    type:        Optional[str] = Query("opinions"),
):
    params = {k: v for k, v in {
        "q": q, "type": "r" if type=="dockets" else "o",
        "order_by": "score desc", "court": court,
        "filed_after": filed_after, "page_size": limit, "format": "json",
    }.items() if v}
    try:
        resp = requests.get(f"{CL_BASE}/search/", params=params,
                            headers=cl_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {"success": True, "count": data.get("count",0),
                "results": data.get("results",[])}
    except Exception as e:
        raise HTTPException(502, f"CourtListener search failed: {e}")


@router.get("/courtlistener/opinion/{opinion_id}")
async def cl_opinion(
    opinion_id:         int,
    run_nlp:            bool           = Query(True),
    case_management_id: Optional[int]  = Query(None),
):
    try:
        resp = requests.get(f"{CL_BASE}/opinions/{opinion_id}/",
                            params={"format":"json"},
                            headers=cl_headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"CourtListener fetch failed: {e}")

    text = (data.get("plain_text") or
            re.sub(r"<[^>]+>"," ", data.get("html_with_citations","")) or "").strip()

    response = {
        "success": True, "opinion_id": opinion_id,
        "text_chars": len(text), "preview": text[:500],
        "meta": {
            "case_name":  data.get("cluster",{}).get("case_name",""),
            "date_filed": data.get("cluster",{}).get("date_filed",""),
        }
    }

    if run_nlp and text:
        doc_name = response["meta"].get("case_name") or f"Opinion_{opinion_id}"
        nlp = run_nlp_pipeline(text)
        response["nlp"] = {k: v for k, v in nlp.items()
                           if k not in ("events","entities")}
        response["nlp"]["event_count"]  = len(nlp.get("events",[]))
        response["nlp"]["entity_count"] = len(nlp.get("entities",[]))
        if case_management_id:
            response["added_to_case"] = add_to_case(
                case_management_id, doc_name, text, nlp, source="pacer")

    return response


@router.get("/courtlistener/docket/{docket_id}")
async def cl_docket(docket_id: int):
    try:
        resp = requests.get(f"{CL_BASE}/dockets/{docket_id}/",
                            params={"format":"json"},
                            headers=cl_headers(), timeout=15)
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}
    except Exception as e:
        raise HTTPException(502, f"CourtListener docket fetch failed: {e}")
